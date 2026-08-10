"""The auth resolvers must be armed before the first request, not after it.

Found in production: a real key returned 401 "API key authentication is not
configured". The resolvers were registered inside Gateway.__init__, but
authentication is a FastAPI dependency and runs strictly BEFORE the route
handler — and the handler is the only caller of gw(). So on an instance whose
first caller presented an API key, nothing had built a Gateway yet, the
request 401'd, the handler never ran, and the Gateway that would have
registered the resolver was never built. The feature could not bootstrap
itself; it worked only where a signed-in user happened to arrive first.

The suspension resolver shared the defect with a worse failure mode: unset,
it fails open, so a suspended workspace kept working.

These tests import the module the way a cold container does and assert the
resolvers are already installed, and that installing them did not eagerly
build a Gateway (which would put Firestore, BigQuery and Storage clients on
the import path, where a failure crashes the container instead of degrading).
"""

from __future__ import annotations

import pytest

import auth_middleware
from api_gateway.composition import register_auth_resolvers


@pytest.fixture(autouse=True)
def _restore_resolvers():
    """These are module-level singletons; leaving a test double installed
    would silently change how every later test authenticates."""
    saved = (auth_middleware._api_key_resolver, auth_middleware._tenant_status_resolver)
    yield
    auth_middleware._api_key_resolver, auth_middleware._tenant_status_resolver = saved


def _cold_start():
    """Re-execute main.py the way a fresh container does.

    A plain `import` is cached, so it would assert nothing here — the
    module-level registration only runs on first execution. Reloading is what
    actually reproduces a cold Cloud Run instance.
    """
    import importlib

    import api_gateway.main as main

    auth_middleware.set_api_key_resolver(None)
    auth_middleware.set_tenant_status_resolver(None)
    importlib.reload(main)


class TestArmedByStartupAlone:
    def test_the_api_key_resolver_is_registered(self):
        """The exact production symptom: this was None on a cold instance,
        and no API-key request could ever make it non-None."""
        _cold_start()
        assert auth_middleware._api_key_resolver is not None

    def test_the_tenant_status_resolver_is_registered(self):
        """Unset, this fails open and a suspended workspace keeps working."""
        _cold_start()
        assert auth_middleware._tenant_status_resolver is not None


class TestRegistrationStaysCheap:
    def test_registering_does_not_build_a_gateway(self):
        """Lazily, inside the closure — not on the import path.

        Building eagerly would open Firestore, BigQuery and Storage clients
        during import, turning a transient datastore failure at boot into a
        container that will not start.
        """
        built = []
        register_auth_resolvers(lambda: built.append(1))
        assert built == []

    def test_a_malformed_key_is_rejected_without_building_a_gateway(self):
        """Junk headers must not be able to force datastore construction."""
        built = []

        def factory():
            built.append(1)
            raise AssertionError("gateway must not be built for a junk key")

        register_auth_resolvers(factory)
        assert auth_middleware._api_key_resolver("not-a-key") is None
        assert built == []

    def test_a_well_formed_key_does_reach_the_datastore(self):
        """The laziness must not be so lazy that real keys stop resolving."""
        from api_keys import generate_api_key

        calls = []

        class Repo:
            def find_api_key_by_hash(self, h):
                calls.append(h)
                return None

        register_auth_resolvers(lambda: type("G", (), {"repo": Repo()})())
        assert auth_middleware._api_key_resolver(generate_api_key().plaintext) is None
        assert len(calls) == 1
