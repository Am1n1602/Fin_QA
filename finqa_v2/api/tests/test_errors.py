import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from finqa_v2.api.errors import ApiError, CompanyNotFoundError, install_exception_handlers


def _app():
    app = FastAPI()
    install_exception_handlers(app)

    @app.get("/boom-api")
    def boom_api():
        raise CompanyNotFoundError("ZZZ")

    @app.get("/boom-custom")
    def boom_custom():
        err = ApiError("nope")
        err.status_code, err.error_code = 429, "rate_limited"
        raise err

    @app.get("/boom-unhandled")
    def boom_unhandled():
        raise ValueError("kaboom")

    return app


class Errors(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(_app(), raise_server_exceptions=False)

    def test_company_not_found_shape(self):
        r = self.client.get("/boom-api")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json(), {"error": "company_not_found",
                                    "detail": "No company with ticker 'ZZZ' in the database."})

    def test_custom_status_and_code_on_instance(self):
        r = self.client.get("/boom-custom")
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.json()["error"], "rate_limited")

    def test_unhandled_exception_never_leaks_internals(self):
        r = self.client.get("/boom-unhandled")
        self.assertEqual(r.status_code, 500)
        body = r.json()
        self.assertEqual(body["error"], "internal_error")
        self.assertNotIn("kaboom", body["detail"])
        self.assertIn("ValueError", body["detail"])


if __name__ == "__main__":
    unittest.main()
