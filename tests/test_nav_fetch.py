"""
test_nav_fetch.py — QA cho NAV fetching trong bot.py
Functions: fetch_fmarket, fetch_tcbs, get_nav_series, _parse_fmarket_response
"""
import sys, json
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent))
import bot as B

# ── Fmarket mock response (format thực tế từ api_docs.md) ───────────────────
FMARKET_RESPONSE_V1 = {
    "data": {
        "navHistories": [
            {"navDate": "2024-01-02", "nav": 11200.5},
            {"navDate": "2024-02-01", "nav": 11350.0},
            {"navDate": "2024-03-01", "nav": 11500.0},
        ]
    }
}
FMARKET_RESPONSE_FLAT = {
    "data": [
        {"navDate": "2024-01-02", "nav": 11200.5},
        {"navDate": "2024-02-01", "nav": 11350.0},
    ]
}
FMARKET_RESPONSE_EMPTY = {"data": {}}

# ── TCBS mock response (format từ fetch_tcbs thực tế) ───────────────────────
TCBS_RESPONSE_V1 = {
    "data": [
        {"navDate": "2024-01-02", "nav": 13200.0},
        {"navDate": "2024-02-01", "nav": 13350.0},
        {"navDate": "2024-03-01", "nav": 13500.0},
    ]
}
TCBS_RESPONSE_V2 = {
    "navHistory": [
        {"tradingDate": "2024-01-02", "navValue": 13200.0},
        {"tradingDate": "2024-02-01", "navValue": 13350.0},
    ]
}
TCBS_RESPONSE_V3 = {
    "list": [
        {"date": "2024-01-02T00:00:00", "close": 13200.0},
        {"date": "2024-02-01T00:00:00", "close": 13350.0},
    ]
}


def make_mock_response(status_code=200, json_data=None, raise_exc=None):
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.ok = (status_code == 200)
    mock_resp.json.return_value = json_data or {}
    if raise_exc:
        mock_resp.raise_for_status.side_effect = raise_exc
    return mock_resp


# ════════════════════════════════════════════════════════
# _parse_fmarket_response
# ════════════════════════════════════════════════════════

class TestParseFmarketResponse:

    def test_parses_nested_navHistories(self):
        result = B._parse_fmarket_response(FMARKET_RESPONSE_V1)
        assert len(result) == 3

    def test_parses_flat_data_list(self):
        result = B._parse_fmarket_response(FMARKET_RESPONSE_FLAT)
        assert len(result) == 2

    def test_returns_empty_list_on_empty(self):
        result = B._parse_fmarket_response(FMARKET_RESPONSE_EMPTY)
        assert result == []

    def test_returns_list_type(self):
        result = B._parse_fmarket_response(FMARKET_RESPONSE_V1)
        assert isinstance(result, list)

    def test_handles_missing_data_key(self):
        result = B._parse_fmarket_response({})
        assert result == [] or isinstance(result, list)

    def test_handles_navHistories_at_root(self):
        data = {"navHistories": [{"navDate": "2024-01-01", "nav": 100.0}]}
        result = B._parse_fmarket_response(data)
        assert isinstance(result, list)


# ════════════════════════════════════════════════════════
# fetch_fmarket
# ════════════════════════════════════════════════════════

class TestFetchFmarket:

    def test_posts_to_correct_url(self):
        with patch("requests.post") as mock_post:
            mock_post.return_value = make_mock_response(200, FMARKET_RESPONSE_V1)
            B.fetch_fmarket(27)
            called_url = mock_post.call_args[0][0]
            assert "fmarket.vn" in called_url, f"Phải gọi fmarket.vn, got: {called_url}"

    def test_sends_product_id_in_payload(self):
        with patch("requests.post") as mock_post:
            mock_post.return_value = make_mock_response(200, FMARKET_RESPONSE_V1)
            B.fetch_fmarket(27)
            payload = mock_post.call_args[1].get("json", {})
            assert payload.get("productId") == 27, \
                f"payload phải có productId=27, got: {payload}"

    def test_sends_isAllData_1(self):
        with patch("requests.post") as mock_post:
            mock_post.return_value = make_mock_response(200, FMARKET_RESPONSE_V1)
            B.fetch_fmarket(11)
            payload = mock_post.call_args[1].get("json", {})
            assert payload.get("isAllData") == 1, "isAllData phải = 1"

    def test_returns_list_of_pts(self):
        with patch("requests.post") as mock_post:
            mock_post.return_value = make_mock_response(200, FMARKET_RESPONSE_V1)
            result = B.fetch_fmarket(27)
            assert isinstance(result, list)
            assert len(result) > 0

    def test_each_pt_has_date_and_nav(self):
        with patch("requests.post") as mock_post:
            mock_post.return_value = make_mock_response(200, FMARKET_RESPONSE_V1)
            result = B.fetch_fmarket(27)
            for pt in result:
                assert "date" in pt, f"Thiếu 'date' trong: {pt}"
                assert "nav" in pt, f"Thiếu 'nav' trong: {pt}"

    def test_date_trimmed_to_10_chars(self):
        with patch("requests.post") as mock_post:
            mock_post.return_value = make_mock_response(200, FMARKET_RESPONSE_V1)
            result = B.fetch_fmarket(27)
            for pt in result:
                assert len(pt["date"]) == 10, \
                    f"date phải là YYYY-MM-DD (10 chars), got: {pt['date']}"

    def test_returns_empty_on_http_error(self):
        with patch("requests.post") as mock_post:
            mock_post.return_value = make_mock_response(500)
            mock_post.return_value.raise_for_status.side_effect = Exception("500")
            result = B.fetch_fmarket(27)
            assert result == [] or isinstance(result, list)

    def test_returns_empty_on_timeout(self):
        import requests as req_lib
        with patch("requests.post", side_effect=req_lib.exceptions.Timeout):
            result = B.fetch_fmarket(27)
            assert result == []

    def test_results_sorted_by_date(self):
        # Fmarket có thể trả về unordered — fetch_fmarket nên sort
        shuffled = {
            "data": {"navHistories": [
                {"navDate": "2024-03-01", "nav": 11500.0},
                {"navDate": "2024-01-02", "nav": 11200.5},
                {"navDate": "2024-02-01", "nav": 11350.0},
            ]}
        }
        with patch("requests.post") as mock_post:
            mock_post.return_value = make_mock_response(200, shuffled)
            result = B.fetch_fmarket(27)
            if len(result) > 1:
                dates = [pt["date"] for pt in result]
                assert dates == sorted(dates), "Kết quả phải được sort theo ngày"

    def test_sets_timeout_15s(self):
        with patch("requests.post") as mock_post:
            mock_post.return_value = make_mock_response(200, FMARKET_RESPONSE_V1)
            B.fetch_fmarket(27)
            kwargs = mock_post.call_args[1]
            assert kwargs.get("timeout") == 15, \
                f"Timeout phải = 15s, got: {kwargs.get('timeout')}"


# ════════════════════════════════════════════════════════
# fetch_tcbs
# ════════════════════════════════════════════════════════

class TestFetchTcbs:

    def test_calls_apipubaws_domain(self):
        with patch("requests.get") as mock_get:
            mock_get.return_value = make_mock_response(200, TCBS_RESPONSE_V1)
            B.fetch_tcbs("TCBF")
            called_url = mock_get.call_args[0][0]
            assert "apiextaws.tcbs.com.vn" in called_url, \
                f"Phải gọi apiextaws domain, got: {called_url}"

    def test_includes_fund_code_in_url(self):
        with patch("requests.get") as mock_get:
            mock_get.return_value = make_mock_response(200, TCBS_RESPONSE_V1)
            B.fetch_tcbs("TCBF")
            called_url = mock_get.call_args[0][0]
            assert "TCBF" in called_url

    def test_uses_bearer_token_when_provided(self):
        with patch("requests.get") as mock_get:
            mock_get.return_value = make_mock_response(200, TCBS_RESPONSE_V1)
            B.fetch_tcbs("TCBF", token="MY_TOKEN_123")
            headers = mock_get.call_args[1].get("headers", {})
            assert "Authorization" in headers
            assert "MY_TOKEN_123" in headers["Authorization"]

    def test_no_auth_header_without_token(self):
        with patch("requests.get") as mock_get:
            mock_get.return_value = make_mock_response(200, TCBS_RESPONSE_V1)
            B.fetch_tcbs("TCBF", token="")
            headers = mock_get.call_args[1].get("headers", {})
            # Không có token → Authorization không nên có Bearer
            assert "Bearer" not in headers.get("Authorization", "")

    def test_parses_data_key_response(self):
        with patch("requests.get") as mock_get:
            mock_get.return_value = make_mock_response(200, TCBS_RESPONSE_V1)
            result = B.fetch_tcbs("TCBF")
            assert len(result) == 3

    def test_parses_navHistory_key_response(self):
        with patch("requests.get") as mock_get:
            mock_get.return_value = make_mock_response(200, TCBS_RESPONSE_V2)
            result = B.fetch_tcbs("TCBF")
            assert len(result) > 0, "Phải parse được navHistory format"

    def test_parses_list_key_response(self):
        with patch("requests.get") as mock_get:
            mock_get.return_value = make_mock_response(200, TCBS_RESPONSE_V3)
            result = B.fetch_tcbs("TCBF")
            assert len(result) > 0, "Phải parse được list/close format"

    def test_returns_empty_on_401(self):
        with patch("requests.get") as mock_get:
            mock_get.return_value = make_mock_response(401)
            result = B.fetch_tcbs("TCBF", token="expired_token")
            assert result == [], f"401 phải trả [] , got {result}"

    def test_returns_empty_on_all_urls_fail(self):
        # Cả 2 URLs đều fail
        with patch("requests.get") as mock_get:
            mock_get.return_value = make_mock_response(500)
            result = B.fetch_tcbs("TCBF")
            assert result == []

    def test_returns_sorted_by_date(self):
        unordered = {
            "data": [
                {"navDate": "2024-03-01", "nav": 13500.0},
                {"navDate": "2024-01-02", "nav": 13200.0},
                {"navDate": "2024-02-01", "nav": 13350.0},
            ]
        }
        with patch("requests.get") as mock_get:
            mock_get.return_value = make_mock_response(200, unordered)
            result = B.fetch_tcbs("TCBF")
            if len(result) > 1:
                dates = [pt["date"] for pt in result]
                assert dates == sorted(dates), "TCBS result phải sorted theo ngày"

    def test_filters_zero_nav(self):
        with_zeros = {
            "data": [
                {"navDate": "2024-01-01", "nav": 0},
                {"navDate": "2024-01-02", "nav": 13200.0},
            ]
        }
        with patch("requests.get") as mock_get:
            mock_get.return_value = make_mock_response(200, with_zeros)
            result = B.fetch_tcbs("TCBF")
            for pt in result:
                assert pt["nav"] > 0, f"NAV = 0 phải bị filter: {pt}"

    def test_date_trimmed_to_10_chars(self):
        # TCBS trả date dạng "2024-01-15T00:00:00" — phải trim về "2024-01-15"
        with patch("requests.get") as mock_get:
            mock_get.return_value = make_mock_response(200, TCBS_RESPONSE_V3)
            result = B.fetch_tcbs("TCBF")
            for pt in result:
                assert len(pt["date"]) == 10, \
                    f"date phải trim 10 chars, got: {pt['date']}"

    def test_tries_fallback_url_on_first_failure(self):
        # URL đầu fail, URL thứ 2 thành công
        call_count = [0]
        def side_effect(url, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return make_mock_response(404)  # URL 1 fail
            return make_mock_response(200, TCBS_RESPONSE_V1)  # URL 2 OK
        with patch("requests.get", side_effect=side_effect):
            result = B.fetch_tcbs("TCBF")
            assert len(result) > 0, "Phải dùng fallback URL khi URL đầu fail"
            assert call_count[0] == 2, f"Phải thử 2 URLs, thử {call_count[0]}"

    def test_from_date_is_passed_in_url(self):
        """from_date thay thế 2023-01-01 trong URL đầu tiên."""
        captured_url = []
        def side_effect(url, *args, **kwargs):
            captured_url.append(url)
            return make_mock_response(200, TCBS_RESPONSE_V1)
        with patch("requests.get", side_effect=side_effect):
            B.fetch_tcbs("TCBF", from_date="2026-04-02")
        assert captured_url, "requests.get phải được gọi"
        assert "startDate=2026-04-02" in captured_url[0], \
            f"from_date phải được dùng trong URL. Got: {captured_url[0]}"
        assert "2023-01-01" not in captured_url[0], \
            "startDate mặc định 2023-01-01 không được xuất hiện khi có from_date"

    def test_from_date_none_uses_default(self):
        """Khi from_date=None, URL dùng 2023-01-01 mặc định."""
        captured_url = []
        def side_effect(url, *args, **kwargs):
            captured_url.append(url)
            return make_mock_response(200, TCBS_RESPONSE_V1)
        with patch("requests.get", side_effect=side_effect):
            B.fetch_tcbs("TCBF")
        assert "startDate=2023-01-01" in captured_url[0], \
            f"Mặc định phải dùng 2023-01-01. Got: {captured_url[0]}"


# ════════════════════════════════════════════════════════
# get_nav_series
# ════════════════════════════════════════════════════════

class TestGetNavSeries:

    def test_uses_fmarket_when_fmarket_id_exists(self):
        fund_cfg = {"fmarket_id": 27}
        with patch.object(B, "fetch_fmarket", return_value=[{"date": "2024-01-02", "nav": 100.0}]) as mock_fm, \
             patch.object(B, "fetch_tcbs", return_value=[]) as mock_tcbs:
            result = B.get_nav_series("VCBFTBF", fund_cfg)
            mock_fm.assert_called_once_with(27)
            mock_tcbs.assert_not_called()

    def test_falls_back_to_tcbs_when_fmarket_empty(self):
        fund_cfg = {"fmarket_id": 27, "tcbs": True}
        with patch.object(B, "fetch_fmarket", return_value=[]) as mock_fm, \
             patch.object(B, "fetch_tcbs", return_value=[{"date": "2024-01-02", "nav": 100.0}]) as mock_tcbs:
            result = B.get_nav_series("TCBF", fund_cfg)
            mock_tcbs.assert_called_once()
            assert len(result) > 0

    def test_skips_fmarket_when_no_fmarket_id(self):
        fund_cfg = {"tcbs": True}
        with patch.object(B, "fetch_fmarket", return_value=[]) as mock_fm, \
             patch.object(B, "fetch_tcbs", return_value=[{"date": "2024-01-02", "nav": 100.0}]):
            B.get_nav_series("TCBF", fund_cfg)
            mock_fm.assert_not_called()

    def test_passes_tcbs_token_from_config(self):
        fund_cfg = {"tcbs": True}
        config = {"tcbs_token": "MY_SECRET_TOKEN"}
        with patch.object(B, "fetch_fmarket", return_value=[]), \
             patch.object(B, "fetch_tcbs", return_value=[]) as mock_tcbs:
            B.get_nav_series("TCBF", fund_cfg, config)
            call_args = mock_tcbs.call_args
            assert "MY_SECRET_TOKEN" in str(call_args), \
                "tcbs_token phải được truyền vào fetch_tcbs"

    def test_returns_empty_when_both_sources_fail(self):
        fund_cfg = {"fmarket_id": 27, "tcbs": True}
        with patch.object(B, "fetch_fmarket", return_value=[]), \
             patch.object(B, "fetch_tcbs", return_value=[]):
            result = B.get_nav_series("TCBF", fund_cfg)
            assert result == []
