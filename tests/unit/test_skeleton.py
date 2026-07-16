"""Skeleton sanity: the package imports whole and declares a contract version."""

import importlib
import pkgutil

import argus


def test_all_modules_import():
    for module in pkgutil.walk_packages(argus.__path__, "argus."):
        importlib.import_module(module.name)


def test_contract_version_declared():
    assert isinstance(argus.CONTRACT_VERSION, str)
    assert argus.CONTRACT_VERSION
