#!/usr/bin/env python3
"""Simple test: initialize VitalSigns singleton and exit, logging INFO to file."""

import sys
import logging

LOG_FILE = "vitalsigns_init.log"


def setup_logging():
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")

    fh = logging.FileHandler(LOG_FILE, mode="w")
    fh.setLevel(logging.INFO)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    root.addHandler(ch)


def main():
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("Starting VitalSigns init test")

    from vital_ai_vitalsigns.vitalsigns import VitalSigns

    logger.info("Imported VitalSigns class")

    vs = VitalSigns()

    logger.info("VitalSigns singleton initialised: %s", vs)
    logger.info("Test complete – log written to %s", LOG_FILE)


if __name__ == "__main__":
    main()
