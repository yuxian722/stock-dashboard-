"""Client-side helpers for ChipMOS's internal "Mapping" SOAP service
(http://tneas.tn.chipmos.com.tw:10000/Mapping/Service.asmx).

That host is only reachable from ChipMOS's internal network, so this module
only builds requests and parses responses — the actual HTTP call is left to
`fetch_mapping_lots`, which the caller runs from a machine on that network.
Request/response shapes here are unit tested against real captured bodies,
not guessed from the WSDL alone.

Confirmed empirically (2026-08-14, live queries against production):
- `assy_lot` must be the BASE lot code with the sub-lot suffix stripped —
  e.g. "V32AWCW", not "V32AWCW01" or "V32AWCW02". The suffixed form returns
  an empty result even for a sub-lot confirmed to be actively running on
  the floor at query time.
- A successful GetMappingLotNoByAssyLot response is a comma-separated list
  of MAPPING_LOT values: one assy_lot base can span multiple wafers.
- GetAOIBinData did not return usable data for a real, correctly-formatted
  assy_lot (STATUS=NG) — despite its name, it does not appear to be the
  source of the wafer die-pick bin map WaferCoordinate.exe renders. That
  data source is still unresolved; see bingomap/README.md.
"""
from __future__ import annotations

import re
from urllib.request import Request, urlopen

SERVICE_URL = "http://tneas.tn.chipmos.com.tw:10000/Mapping/Service.asmx"
NAMESPACE = "http://tempuri.org/"

_SUB_LOT_SUFFIX_RE = re.compile(r"\d+$")


def strip_sub_lot_suffix(assy_lot: str) -> str:
    """"V32AWCW01" / "V32AWCW02" -> "V32AWCW".

    The Mapping service only recognises the base lot code; querying with
    the sub-lot-suffixed form silently returns no results.
    """
    return _SUB_LOT_SUFFIX_RE.sub("", assy_lot)


def _build_single_param_request(operation: str, param_name: str, param_value: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        'xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">\n'
        "  <soap:Body>\n"
        f'    <{operation} xmlns="{NAMESPACE}">\n'
        f"      <{param_name}>{param_value}</{param_name}>\n"
        f"    </{operation}>\n"
        "  </soap:Body>\n"
        "</soap:Envelope>"
    )


def build_get_mapping_lot_request(assy_lot: str) -> str:
    return _build_single_param_request("GetMappingLotNoByAssyLot", "assy_lot", assy_lot)


GET_MAPPING_LOT_SOAP_ACTION = f"{NAMESPACE}GetMappingLotNoByAssyLot"

_RESULT_PATTERN = re.compile(
    r"<GetMappingLotNoByAssyLotResult(?:\s*/>|>(?P<content>.*?)</GetMappingLotNoByAssyLotResult>)",
    re.DOTALL,
)


def parse_mapping_lot_response(soap_xml: str) -> list[str]:
    """Extract the comma-separated MAPPING_LOT list from a
    GetMappingLotNoByAssyLotResponse body.

    Empty list if the lot wasn't found — the service returns a self-closing
    result element (`<GetMappingLotNoByAssyLotResult />`) in that case
    rather than an error.
    """
    match = _RESULT_PATTERN.search(soap_xml)
    if match is None:
        raise ValueError(
            f"response did not contain GetMappingLotNoByAssyLotResult: {soap_xml!r}"
        )
    content = match.group("content")
    if not content:
        return []
    return [lot.strip() for lot in content.split(",") if lot.strip()]


def fetch_mapping_lots(assy_lot: str, *, timeout: float = 10.0) -> list[str]:
    """Query the live service. Only works from ChipMOS's internal network.

    Strips the sub-lot suffix automatically — pass either "V32AWCW" or
    "V32AWCW01" and the same base lot is queried.
    """
    request_body = build_get_mapping_lot_request(strip_sub_lot_suffix(assy_lot))
    request = Request(
        SERVICE_URL,
        data=request_body.encode("utf-8"),
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": GET_MAPPING_LOT_SOAP_ACTION,
        },
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return parse_mapping_lot_response(body)
