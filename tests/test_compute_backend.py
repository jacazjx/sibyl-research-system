"""Tests for the pluggable compute backend abstraction."""

import pytest

from sibyl.config import Config
from sibyl.compute import get_backend
from sibyl.compute.local_backend import LocalBackend
from sibyl.compute.ssh_backend import SSHBackend


class TestGetBackend:
    def test_local_backend_is_default(self):
        config = Config()
        backend = get_backend(config, "/tmp/ws")
        assert isinstance(backend, LocalBackend)
        assert backend.backend_type == "local"

    def test_ssh_backend(self):
        config = Config()
        config.compute_backend = "ssh"
        backend = get_backend(config, "/tmp/ws")
        assert isinstance(backend, SSHBackend)
        assert backend.backend_type == "ssh"

    def test_invalid_backend_raises(self):
        config = Config()
        config.compute_backend = "slurm"
        with pytest.raises(ValueError, match="Unknown compute_backend"):
            get_backend(config, "/tmp/ws")


class TestLocalBackend:
    def _make_backend(self, **config_overrides):
        config = Config()
        for k, v in config_overrides.items():
            setattr(config, k, v)
        return LocalBackend.from_config(config, "/tmp/workspace/active")

    def test_project_dir_is_active_root(self):
        backend = self._make_backend()
        assert backend.project_dir("my-project") == "/tmp/workspace/active"

    def test_env_cmd_conda_default(self):
        backend = self._make_backend()
        cmd = backend.env_cmd("my-project")
        assert "conda run -n sibyl_my-project" in cmd

    def test_env_cmd_conda_custom(self):
        backend = self._make_backend(
            local_conda_path="/opt/conda/bin/conda",
            local_conda_env_name="my_env",
        )
        cmd = backend.env_cmd("my-project")
        assert "/opt/conda/bin/conda run -n my_env" in cmd

    def test_env_cmd_venv(self):
        backend = self._make_backend(local_env_type="venv")
        cmd = backend.env_cmd("my-project")
        assert "source .venv/bin/activate &&" in cmd

    def test_gpu_poll_script_basics(self):
        backend = self._make_backend()
        script = backend.gpu_poll_script(
            candidate_gpu_ids=[0, 1],
            threshold_mb=2000,
            poll_interval_sec=60,
            max_polls=0,
            marker_file="/tmp/marker.json",
            aggressive_mode=False,
            aggressive_threshold_pct=25,
        )
        assert "nvidia-smi" in script
        assert "LOCAL" in script
        assert "/tmp/marker.json" in script

    def test_gpu_poll_script_no_ssh_keyword(self):
        """Local GPU poll script must not contain ssh commands."""
        backend = self._make_backend()
        script = backend.gpu_poll_script(
            candidate_gpu_ids=[0, 1, 2, 3],
            threshold_mb=2000,
            poll_interval_sec=600,
            max_polls=0,
            marker_file="/tmp/test.json",
            aggressive_mode=True,
            aggressive_threshold_pct=25,
        )
        # Remove comment lines to check actual commands
        command_lines = [
            line for line in script.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        for line in command_lines:
            assert "ssh " not in line, f"Found SSH in command: {line}"

    def test_experiment_monitor_script_no_ssh(self):
        backend = self._make_backend()
        script = backend.experiment_monitor_script(
            project_dir="/tmp/workspace/active",
            task_ids=["task_1a", "task_1b"],
            poll_interval_sec=120,
            timeout_minutes=60,
            marker_file="/tmp/monitor.json",
            workspace_path="",
            heartbeat_polls=3,
            task_gpu_map=None,
        )
        assert "LOCAL" in script
        # No SSH commands in the actual check logic
        command_lines = [
            line for line in script.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        for line in command_lines:
            assert "ssh " not in line, f"Found SSH in command: {line}"

    def test_stuck_detection_handles_missing_pid(self):
        """Monitor script should detect stuck tasks when PID file is missing."""
        backend = self._make_backend()
        script = backend.experiment_monitor_script(
            project_dir="/tmp/workspace/active",
            task_ids=["task_a"],
            poll_interval_sec=120,
            timeout_minutes=60,
            marker_file="/tmp/monitor.json",
            workspace_path="/tmp/ws",
            heartbeat_polls=3,
            task_gpu_map=None,
        )
        # Must handle the case where PID file doesn't exist and DONE marker is missing
        assert "_DONE" in script
        # The elif branch should check for no PID + no DONE
        assert "elif" in script


class TestSSHBackend:
    def _make_backend(self, **config_overrides):
        config = Config()
        config.compute_backend = "ssh"
        config.ssh_server = "cs8000d"
        config.remote_base = "/home/user/sibyl"
        for k, v in config_overrides.items():
            setattr(config, k, v)
        return SSHBackend.from_config(config, "")

    def test_project_dir_is_remote(self):
        backend = self._make_backend()
        assert backend.project_dir("my-project") == "/home/user/sibyl/projects/my-project"

    def test_env_cmd_delegates_to_config(self):
        backend = self._make_backend()
        cmd = backend.env_cmd("my-project")
        assert "sibyl_my-project" in cmd

    def test_gpu_poll_script_has_ssh(self):
        backend = self._make_backend()
        script = backend.gpu_poll_script(
            candidate_gpu_ids=[0, 1],
            threshold_mb=2000,
            poll_interval_sec=60,
            max_polls=0,
            marker_file="/tmp/marker.json",
            aggressive_mode=False,
            aggressive_threshold_pct=25,
        )
        assert "ssh cs8000d" in script
        assert "nvidia-smi" in script

    def test_experiment_monitor_script_has_ssh(self):
        backend = self._make_backend()
        script = backend.experiment_monitor_script(
            project_dir="/home/user/sibyl/projects/test",
            task_ids=["task_1a"],
            poll_interval_sec=120,
            timeout_minutes=60,
            marker_file="/tmp/monitor.json",
            workspace_path="",
            heartbeat_polls=3,
            task_gpu_map=None,
        )
        assert "ssh cs8000d" in script


class TestConfigComputeBackend:
    def test_default_is_local(self):
        config = Config()
        assert config.compute_backend == "local"

    def test_local_env_defaults(self):
        config = Config()
        assert config.local_env_type == "conda"
        assert config.local_conda_path == ""
        assert config.local_conda_env_name == ""

    def test_get_local_env_cmd_conda(self):
        config = Config()
        cmd = config.get_local_env_cmd("test-proj")
        assert "conda run -n sibyl_test-proj" in cmd

    def test_get_local_env_cmd_venv(self):
        config = Config()
        config.local_env_type = "venv"
        cmd = config.get_local_env_cmd("test-proj")
        assert "source .venv/bin/activate &&" in cmd

    def test_yaml_roundtrip(self, tmp_path):
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text(
            "compute_backend: ssh\n"
            "local_env_type: venv\n"
            "local_conda_path: /opt/conda\n"
            "local_conda_env_name: my_env\n"
        )
        config = Config.from_yaml(str(config_yaml))
        assert config.compute_backend == "ssh"
        assert config.local_env_type == "venv"
        assert config.local_conda_path == "/opt/conda"
        assert config.local_conda_env_name == "my_env"

    def test_invalid_compute_backend_raises(self, tmp_path):
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text("compute_backend: kubernetes\n")
        with pytest.raises(ValueError, match="compute_backend"):
            Config.from_yaml(str(config_yaml))

    def test_invalid_local_env_type_raises(self, tmp_path):
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text("local_env_type: docker\n")
        with pytest.raises(ValueError, match="local_env_type"):
            Config.from_yaml(str(config_yaml))
