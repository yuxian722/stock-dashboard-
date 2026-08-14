from bingomap.mapping_service import (
    build_get_mapping_lot_request,
    parse_mapping_lot_response,
    strip_sub_lot_suffix,
)

# Captured verbatim from a live PowerShell Invoke-WebRequest against
# http://tneas.tn.chipmos.com.tw:10000/Mapping/Service.asmx on 2026-08-14.
REAL_SUCCESS_RESPONSE = (
    '<?xml version="1.0" encoding="utf-8"?><soap:Envelope '
    'xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
    'xmlns:xsd="http://www.w3.org/2001/XMLSchema"><soap:Body>'
    '<GetMappingLotNoByAssyLotResponse xmlns="http://tempuri.org/">'
    "<GetMappingLotNoByAssyLotResult>8P065800A1,8P065800A6,8P065800A7,8P065800A8"
    "</GetMappingLotNoByAssyLotResult></GetMappingLotNoByAssyLotResponse>"
    "</soap:Body></soap:Envelope>"
)

REAL_EMPTY_RESPONSE = (
    '<?xml version="1.0" encoding="utf-8"?><soap:Envelope '
    'xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
    'xmlns:xsd="http://www.w3.org/2001/XMLSchema"><soap:Body>'
    '<GetMappingLotNoByAssyLotResponse xmlns="http://tempuri.org/">'
    "<GetMappingLotNoByAssyLotResult /></GetMappingLotNoByAssyLotResponse>"
    "</soap:Body></soap:Envelope>"
)


def test_strip_sub_lot_suffix_removes_trailing_digits():
    assert strip_sub_lot_suffix("V32AWCW01") == "V32AWCW"
    assert strip_sub_lot_suffix("V32AWCW02") == "V32AWCW"
    assert strip_sub_lot_suffix("V32AWCW") == "V32AWCW"


def test_parse_real_success_response_returns_all_mapping_lots():
    assert parse_mapping_lot_response(REAL_SUCCESS_RESPONSE) == [
        "8P065800A1",
        "8P065800A6",
        "8P065800A7",
        "8P065800A8",
    ]


def test_parse_real_empty_response_returns_empty_list():
    assert parse_mapping_lot_response(REAL_EMPTY_RESPONSE) == []


def test_parse_raises_on_unrelated_response():
    import pytest

    with pytest.raises(ValueError):
        parse_mapping_lot_response("<soap:Envelope></soap:Envelope>")


def test_build_request_embeds_assy_lot_and_operation_name():
    body = build_get_mapping_lot_request("V32AWCW")
    assert "<GetMappingLotNoByAssyLot " in body
    assert "<assy_lot>V32AWCW</assy_lot>" in body
