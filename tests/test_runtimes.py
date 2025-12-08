"""Tests for RuntimeConfig and runtimes module."""

import pytest

from pydantic_deep.runtimes import BUILTIN_RUNTIMES, get_runtime
from pydantic_deep.types import RuntimeConfig


class TestRuntimeConfig:
    """Tests for RuntimeConfig model."""

    def test_minimal_config(self):
        """Test creating a minimal runtime config."""
        config = RuntimeConfig(name="test")
        assert config.name == "test"
        assert config.description == ""
        assert config.image is None
        assert config.base_image is None
        assert config.packages == []
        assert config.package_manager == "pip"
        assert config.setup_commands == []
        assert config.env_vars == {}
        assert config.work_dir == "/workspace"
        assert config.cache_image is True

    def test_full_config(self):
        """Test creating a full runtime config."""
        config = RuntimeConfig(
            name="full-test",
            description="Full test config",
            base_image="python:3.12",
            packages=["pandas", "numpy"],
            package_manager="pip",
            setup_commands=["apt-get update"],
            env_vars={"DEBUG": "true"},
            work_dir="/app",
            cache_image=False,
        )
        assert config.name == "full-test"
        assert config.description == "Full test config"
        assert config.base_image == "python:3.12"
        assert config.packages == ["pandas", "numpy"]
        assert config.package_manager == "pip"
        assert config.setup_commands == ["apt-get update"]
        assert config.env_vars == {"DEBUG": "true"}
        assert config.work_dir == "/app"
        assert config.cache_image is False

    def test_image_config(self):
        """Test config with ready-to-use image."""
        config = RuntimeConfig(
            name="prebuilt",
            image="myregistry/my-image:v1",
        )
        assert config.image == "myregistry/my-image:v1"
        assert config.base_image is None

    def test_package_managers(self):
        """Test different package managers."""
        for pm in ["pip", "npm", "apt", "cargo"]:
            config = RuntimeConfig(name="test", package_manager=pm)
            assert config.package_manager == pm

    def test_invalid_package_manager(self):
        """Test that invalid package manager raises error."""
        with pytest.raises(ValueError):
            RuntimeConfig(name="test", package_manager="invalid")

    def test_model_dump_json(self):
        """Test JSON serialization for hashing."""
        config = RuntimeConfig(
            name="test",
            packages=["pkg1", "pkg2"],
        )
        json_str = config.model_dump_json()
        assert "test" in json_str
        assert "pkg1" in json_str


class TestBuiltinRuntimes:
    """Tests for built-in runtime configurations."""

    def test_python_minimal(self):
        """Test python-minimal runtime."""
        runtime = BUILTIN_RUNTIMES["python-minimal"]
        assert runtime.name == "python-minimal"
        assert runtime.image == "python:3.12-slim"
        assert runtime.packages == []

    def test_python_datascience(self):
        """Test python-datascience runtime."""
        runtime = BUILTIN_RUNTIMES["python-datascience"]
        assert runtime.name == "python-datascience"
        assert runtime.base_image == "python:3.12-slim"
        assert "pandas" in runtime.packages
        assert "numpy" in runtime.packages
        assert "matplotlib" in runtime.packages
        assert runtime.package_manager == "pip"

    def test_python_web(self):
        """Test python-web runtime."""
        runtime = BUILTIN_RUNTIMES["python-web"]
        assert runtime.name == "python-web"
        assert "fastapi" in runtime.packages
        assert "uvicorn" in runtime.packages

    def test_node_minimal(self):
        """Test node-minimal runtime."""
        runtime = BUILTIN_RUNTIMES["node-minimal"]
        assert runtime.name == "node-minimal"
        assert runtime.image == "node:20-slim"
        assert runtime.work_dir == "/app"

    def test_node_react(self):
        """Test node-react runtime."""
        runtime = BUILTIN_RUNTIMES["node-react"]
        assert runtime.name == "node-react"
        assert runtime.base_image == "node:20-slim"
        assert "typescript" in runtime.packages
        assert "react" in runtime.packages
        assert runtime.package_manager == "npm"
        assert runtime.work_dir == "/app"

    def test_all_runtimes_valid(self):
        """Test that all built-in runtimes are valid."""
        for name, runtime in BUILTIN_RUNTIMES.items():
            assert runtime.name == name
            assert isinstance(runtime, RuntimeConfig)
            # Must have either image or base_image
            assert runtime.image or runtime.base_image


class TestGetRuntime:
    """Tests for get_runtime function."""

    def test_get_existing_runtime(self):
        """Test getting an existing runtime."""
        runtime = get_runtime("python-datascience")
        assert runtime.name == "python-datascience"
        assert runtime is BUILTIN_RUNTIMES["python-datascience"]

    def test_get_nonexistent_runtime(self):
        """Test getting a non-existent runtime raises KeyError."""
        with pytest.raises(KeyError) as excinfo:
            get_runtime("nonexistent")
        assert "nonexistent" in str(excinfo.value)
        assert "Available:" in str(excinfo.value)

    def test_get_all_runtimes(self):
        """Test that all runtimes can be retrieved."""
        for name in BUILTIN_RUNTIMES:
            runtime = get_runtime(name)
            assert runtime.name == name
