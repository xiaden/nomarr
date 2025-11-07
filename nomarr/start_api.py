#!/usr/bin/env python3
"""
Nomarr API Starter
Runs a single unified API with both public and internal endpoints
"""

import logging

import uvicorn

logging.basicConfig(level=logging.INFO)


if __name__ == "__main__":
    logging.info("Starting Nomarr API on 0.0.0.0:8356...")
    logging.info("  - Public endpoints: /api/v1/tag, /api/v1/list, /api/v1/status/*, etc.")
    logging.info("  - Internal endpoints: /internal/* (requires internal_key)")

    uvicorn.run(
        "nomarr.interfaces.api.api_app:api_app", host="0.0.0.0", port=8356, timeout_keep_alive=90, log_level="info"
    )
