from __future__ import annotations

import hashlib
import io
import re
import shlex
import tarfile
import time
import uuid
from abc import ABC, abstractmethod
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import chardet
import pypdf

from pydantic_deep.types import (
    EditResult,
    ExecuteResponse,
    FileInfo,
    GrepMatch,
    RuntimeConfig,
    WriteResult,
)

if TYPE_CHECKING:
    pass


class BaseSandbox(ABC):
    """Abstract base class for sandbox backends.

    Sandboxes provide isolated environments for executing commands and
    managing files. Subclasses must implement the execute() method.
    """

    def __init__(self, sandbox_id: str | None = None):
        """Initialize the sandbox.

        Args:
            sandbox_id: Unique identifier for this sandbox. Generated if not provided.
        """
        self._id = sandbox_id or str(uuid.uuid4())  # pragma: no cover

    @property
    def id(self) -> str:
        """Unique identifier for this sandbox."""
        return self._id  # pragma: no cover

    @abstractmethod
    def execute(
        self, command: str, timeout: int | None = None
    ) -> ExecuteResponse:  # pragma: no cover
        """Execute a command in the sandbox.

        Args:
            command: Command to execute.
            timeout: Maximum execution time in seconds.

        Returns:
            ExecuteResponse with output, exit code, and truncation status.
        """
        ...

    def ls_info(self, path: str) -> list[FileInfo]:  # pragma: no cover
        """List files using ls command."""
        path = shlex.quote(path)
        result = self.execute(f"ls -la {path}")
        if result.exit_code != 0:
            return []

        entries: list[FileInfo] = []
        for line in result.output.strip().split("\n")[1:]:  # Skip total line
            if not line.strip():
                continue

            parts = line.split()
            if len(parts) < 9:
                continue

            perms = parts[0]
            size = int(parts[4]) if parts[4].isdigit() else None
            name = " ".join(parts[8:])

            if name in (".", ".."):
                continue

            full_path = f"{path.rstrip('/')}/{name}"
            entries.append(
                FileInfo(
                    name=name,
                    path=full_path,
                    is_dir=perms.startswith("d"),
                    size=size,
                )
            )

        return sorted(entries, key=lambda x: (not x["is_dir"], x["name"]))

    def _read_bytes(self, path: str) -> bytes:  # pragma: no cover
        """Read raw bytes from file using cat command."""
        path = shlex.quote(path)
        result = self.execute(f"cat {path}")

        if result.exit_code != 0:
            return f"[Error: {result.output}]".encode()

        return result.output.encode("utf-8", errors="replace")

    def read(self, path: str, offset: int = 0, limit: int = 2000) -> str:  # pragma: no cover
        """Read file using cat command with line numbers."""
        # Use sed to handle offset and limit
        start = offset + 1  # sed is 1-indexed
        end = offset + limit

        path = shlex.quote(path)
        result = self.execute(f"sed -n '{start},{end}p' {path} | cat -n")

        if result.exit_code != 0:
            return f"Error: {result.output}"

        if result.truncated:
            return result.output + "\n\n... (output truncated)"

        return result.output

    def write(self, path: str, content: str) -> WriteResult:  # pragma: no cover
        """Write file using cat with heredoc."""
        # Escape special characters for heredoc
        escaped = content.replace("\\", "\\\\").replace("$", "\\$").replace("`", "\\`")

        # Use a unique delimiter
        delimiter = f"EOF_{uuid.uuid4().hex[:8]}"

        quoted_path = shlex.quote(path)
        command = (
            f"mkdir -p $(dirname {quoted_path}) && cat > {quoted_path} << '{delimiter}'\n"
            f"{escaped}\n"
            f"{delimiter}"
        )
        result = self.execute(command)

        if result.exit_code != 0:
            return WriteResult(error=result.output)

        return WriteResult(path=path)

    def edit(  # pragma: no cover
        self, path: str, old_string: str, new_string: str, replace_all: bool = False
    ) -> EditResult:
        """Edit file using sed."""
        # First check if file exists and count occurrences
        path = shlex.quote(path)
        check = self.execute(f"grep -c '{old_string}' {path}")

        if check.exit_code != 0:
            if "No such file" in check.output:
                return EditResult(error=f"File '{path}' not found")
            return EditResult(error=f"String '{old_string}' not found in file")

        try:
            occurrences = int(check.output.strip())
        except ValueError:
            occurrences = 0

        if occurrences == 0:
            return EditResult(error=f"String '{old_string}' not found in file")

        if occurrences > 1 and not replace_all:
            return EditResult(
                error=f"String '{old_string}' found {occurrences} times. "
                "Use replace_all=True to replace all, or provide more context."
            )

        # Escape special sed characters
        old_escaped = old_string.replace("/", "\\/").replace("&", "\\&")
        new_escaped = new_string.replace("/", "\\/").replace("&", "\\&")

        if replace_all:
            result = self.execute(f"sed -i 's/{old_escaped}/{new_escaped}/g' {path}")
        else:
            result = self.execute(f"sed -i '0,/{old_escaped}/s//{new_escaped}/' {path}")

        if result.exit_code != 0:
            return EditResult(error=result.output)

        return EditResult(path=path, occurrences=occurrences if replace_all else 1)

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:  # pragma: no cover
        """Find files using find command."""
        # Convert glob to find pattern
        path = shlex.quote(path)
        result = self.execute(f"find {path} -name '{pattern}' -type f 2>/dev/null")

        if result.exit_code != 0:
            return []

        entries: list[FileInfo] = []
        for file_path in result.output.strip().split("\n"):
            if not file_path:
                continue

            name = file_path.split("/")[-1]
            entries.append(
                FileInfo(
                    name=name,
                    path=file_path,
                    is_dir=False,
                    size=None,
                )
            )

        return sorted(entries, key=lambda x: x["path"])

    def grep_raw(  # pragma: no cover
        self, pattern: str, path: str | None = None, glob: str | None = None
    ) -> list[GrepMatch] | str:
        """Search using grep command."""
        search_path = path or "/"

        search_path = shlex.quote(search_path)
        if glob:
            cmd = f"grep -rn '{pattern}' {search_path} --include='{glob}'"
        else:
            cmd = f"grep -rn '{pattern}' {search_path}"

        result = self.execute(cmd)

        if result.exit_code == 1:  # No matches
            return []
        if result.exit_code != 0:
            return f"Error: {result.output}"

        matches: list[GrepMatch] = []
        for line in result.output.strip().split("\n"):
            if not line:
                continue

            # Parse grep output: file:line:content
            parts = line.split(":", 2)
            if len(parts) >= 3:
                try:
                    matches.append(
                        GrepMatch(
                            path=parts[0],
                            line_number=int(parts[1]),
                            line=parts[2],
                        )
                    )
                except ValueError:
                    continue

        return matches


class DockerSandbox(BaseSandbox):  # pragma: no cover
    """Docker-based sandbox for isolated command execution.

    Creates a Docker container for running commands in an isolated environment.
    Requires the docker Python package to be installed.

    Supports RuntimeConfig for pre-configured environments with packages pre-installed.

    Example:
        ```python
        from pydantic_deep import DockerSandbox, RuntimeConfig
        from pydantic_deep.runtimes import BUILTIN_RUNTIMES

        # Use a built-in runtime
        sandbox = DockerSandbox(runtime="python-datascience")

        # Or use a custom runtime
        custom_runtime = RuntimeConfig(
            name="ml-env",
            base_image="python:3.12-slim",
            packages=["torch", "transformers"],
        )
        sandbox = DockerSandbox(runtime=custom_runtime)
        ```
    """

    def __init__(
        self,
        image: str = "python:3.12-slim",
        sandbox_id: str | None = None,
        work_dir: str = "/workspace",
        auto_remove: bool = True,
        runtime: RuntimeConfig | str | None = None,
        session_id: str | None = None,
        idle_timeout: int = 3600,
    ):
        """Initialize Docker sandbox.

        Args:
            image: Docker image to use (ignored if runtime is provided).
            sandbox_id: Unique identifier for this sandbox.
            work_dir: Working directory inside container (ignored if runtime is provided).
            auto_remove: Remove container when stopped.
            runtime: RuntimeConfig or name of built-in runtime.
            session_id: Alias for sandbox_id (for session management).
            idle_timeout: Timeout in seconds for idle cleanup (default: 1 hour).
        """
        # session_id is an alias for sandbox_id
        effective_id = session_id or sandbox_id
        super().__init__(effective_id)

        self._auto_remove = auto_remove
        self._container = None
        self._idle_timeout = idle_timeout
        self._last_activity = time.time()

        # Handle runtime configuration
        if runtime is not None:
            if isinstance(runtime, str):
                from pydantic_deep.runtimes import get_runtime

                runtime = get_runtime(runtime)
            self._runtime: RuntimeConfig | None = runtime
            self._work_dir = runtime.work_dir
            self._image = image  # Will be overridden by _ensure_runtime_image()
        else:
            self._runtime = None
            self._work_dir = work_dir
            self._image = image

    @property
    def runtime(self) -> RuntimeConfig | None:
        """The runtime configuration for this sandbox."""
        return self._runtime

    @property
    def session_id(self) -> str:
        """Alias for sandbox id, used for session management."""
        return self._id

    def _ensure_container(self) -> None:
        """Ensure Docker container is running."""
        if self._container is not None:
            return

        try:
            import docker
        except ImportError as e:
            raise ImportError(
                "Docker package not installed. Install with: pip install docker"
            ) from e

        client = docker.from_env()

        # Get the appropriate image (build if needed for runtime)
        image = self._ensure_runtime_image(client)

        # Prepare environment variables from runtime
        env_vars = {}
        if self._runtime and self._runtime.env_vars:
            env_vars = self._runtime.env_vars

        self._container = client.containers.run(
            image,
            command="sleep infinity",
            detach=True,
            working_dir=self._work_dir,
            auto_remove=self._auto_remove,
            environment=env_vars,
            volumes={},  # Can be configured for persistent storage
        )

    def _ensure_runtime_image(self, client: object) -> str:
        """Ensure runtime image exists and return its name.

        Args:
            client: Docker client instance.

        Returns:
            Docker image name/tag to use.
        """
        if self._runtime is None:
            return self._image

        # If ready-to-use image is specified
        if self._runtime.image:
            return self._runtime.image

        # If base_image + packages - need to build
        if self._runtime.base_image:
            return self._build_runtime_image(client)

        # Fallback to default image
        return self._image

    def _build_runtime_image(self, client: object) -> str:
        """Build a custom image with packages installed.

        Args:
            client: Docker client instance.

        Returns:
            Docker image tag for the built image.
        """
        import docker.errors

        runtime = self._runtime
        assert runtime is not None
        assert runtime.base_image is not None

        # Generate unique tag based on config
        config_hash = hashlib.md5(runtime.model_dump_json().encode()).hexdigest()[:12]
        image_tag = f"pydantic-deep-runtime:{runtime.name}-{config_hash}"

        # Check if image exists (cache)
        if runtime.cache_image:
            try:
                client.images.get(image_tag)  # type: ignore[attr-defined]
                return image_tag
            except docker.errors.ImageNotFound:
                pass

        # Build Dockerfile
        dockerfile = self._generate_dockerfile(runtime)

        # Build image
        client.images.build(  # type: ignore[attr-defined]
            fileobj=io.BytesIO(dockerfile.encode()),
            tag=image_tag,
            rm=True,
        )

        return image_tag

    def _generate_dockerfile(self, runtime: RuntimeConfig) -> str:
        """Generate Dockerfile content for runtime.

        Args:
            runtime: Runtime configuration.

        Returns:
            Dockerfile content as string.
        """
        assert runtime.base_image is not None
        lines = [f"FROM {runtime.base_image}"]

        # Setup commands
        for cmd in runtime.setup_commands:
            lines.append(f"RUN {cmd}")

        # Install packages
        if runtime.packages:
            packages_str = " ".join(runtime.packages)
            if runtime.package_manager == "pip":
                lines.append(f"RUN pip install --no-cache-dir {packages_str}")
            elif runtime.package_manager == "npm":
                lines.append(f"RUN npm install -g {packages_str}")
            elif runtime.package_manager == "apt":
                lines.append(f"RUN apt-get update && apt-get install -y {packages_str}")
            elif runtime.package_manager == "cargo":
                lines.append(f"RUN cargo install {packages_str}")

        # Environment variables
        for key, value in runtime.env_vars.items():
            lines.append(f"ENV {key}={value}")

        # Work directory
        lines.append(f"WORKDIR {runtime.work_dir}")

        return "\n".join(lines)

    def execute(self, command: str, timeout: int | None = None) -> ExecuteResponse:
        """Execute command in Docker container."""
        self._ensure_container()
        self._last_activity = time.time()  # Update activity timestamp
        assert self._container is not None  # Ensured by _ensure_container()

        try:
            # Note: Docker SDK exec_run doesn't support timeout parameter directly.
            # For timeouts, we wrap the command with 'timeout' utility.
            if timeout:
                command = f"timeout {timeout} sh -c {command!r}"
                exec_cmd = ["sh", "-c", command]
            else:
                exec_cmd = ["sh", "-c", command]

            exit_code, output = self._container.exec_run(
                exec_cmd,
                workdir=self._work_dir,
            )

            output_str = output.decode("utf-8", errors="replace")

            # Truncate if too long
            max_output = 100000
            truncated = len(output_str) > max_output
            if truncated:
                output_str = output_str[:max_output]

            return ExecuteResponse(
                output=output_str,
                exit_code=exit_code,
                truncated=truncated,
            )
        except Exception as e:
            return ExecuteResponse(
                output=f"Error: {e}",
                exit_code=1,
                truncated=False,
            )

    def _read_bytes(self, path: str) -> bytes:
        """Read raw bytes from file in container.

        Args:
            path: Path to the file in the container.

        Returns:
            File content as bytes.
        """
        self._ensure_container()
        assert self._container is not None

        try:
            # Use Docker get_archive to read file
            stream, stat = self._container.get_archive(path)
            raw_tar_bytes = b"".join(stream)
        except Exception as e:
            raise RuntimeError(f"Failed to read file: {e}") from e

        # Extract file from tar archive
        with (
            io.BytesIO(raw_tar_bytes) as tar_buffer,
            tarfile.open(fileobj=tar_buffer, mode="r") as tar,
        ):
            member = next((m for m in tar.getmembers() if m.isfile()), None)

            if not member:
                return f"[Error: Path '{path}' exists but is empty or not a file.]".encode()

            f = tar.extractfile(member)
            if f is None:
                return b"[Error: Could not extract file stream from archive]"

            file_bytes = f.read()
            return file_bytes

    def read(self, path: str, offset: int = 0, limit: int = 2000) -> str:
        """
        Read file from container using Docker get_archive API.

        Args:
            path: Path to the file in the container.
            offset: Start line index (for pagination).
            limit: Maximum number of lines to return.
        """
        try:
            # Read raw bytes from file
            file_bytes = self._read_bytes(path)

            # Convert bytes to string
            file_ext = Path(path).suffix.lower().lstrip(".")
            full_text = self._convert_bytes_to_text(file_ext, file_bytes)

            # Split into lines
            lines = full_text.splitlines()
            total_lines = len(lines)

            if offset >= total_lines:
                return "[End of file]"

            end_index = offset + limit
            chunk_lines = lines[offset:end_index]
            chunk = "\n".join(chunk_lines)

            if end_index < total_lines:
                remaining = total_lines - end_index
                footer = f"\n\n[... {remaining} more lines. Use offset={end_index} to read more.]"
                return chunk + footer

            return chunk

        except Exception as e:
            return f"[Error reading file: {e}]"

    def _convert_bytes_to_text(self, file_ext: str, file_bytes: bytes) -> str:
        # Plain text files with encoding detection
        if file_ext in ("txt", "log", "md", "json", "xml", "csv", "yaml", "yml"):
            return self._decode_text(file_bytes)

        # PDF files
        elif file_ext == "pdf":
            return self._extract_pdf_text(file_bytes)

        # Code files
        elif file_ext in (
            "py",
            "js",
            "java",
            "cpp",
            "c",
            "h",
            "cs",
            "rb",
            "go",
            "rs",
            "php",
            "html",
            "css",
            "sh",
            "sql",
            "ts",
            "jsx",
            "tsx",
        ):
            return self._decode_text(file_bytes)

        else:
            raise ValueError(f"Unsupported file type: .{file_ext}")

    def _decode_text(self, file_bytes: bytes) -> str:
        # Use chardet to detect encoding with confidence
        detection = chardet.detect(file_bytes)
        detected_encoding = detection.get("encoding")
        confidence = detection.get("confidence", 0)

        # If high confidence detection, use it
        if detected_encoding and confidence > 0.7:
            try:
                return file_bytes.decode(detected_encoding)
            except (UnicodeDecodeError, AttributeError, LookupError):
                pass  # Fall through to manual attempts

        # Fallback to common encodings if detection failed or low confidence
        encodings = ["utf-8", "utf-8-sig", "latin-1", "cp1252", "iso-8859-1"]

        # Add detected encoding to the front if not already there
        if detected_encoding and detected_encoding not in encodings:
            encodings.insert(0, detected_encoding)

        for encoding in encodings:
            try:
                return file_bytes.decode(encoding)
            except (UnicodeDecodeError, AttributeError, LookupError):
                continue

        # Last resort: decode with errors='replace' to avoid complete failure
        return file_bytes.decode("utf-8", errors="replace")

    def _extract_pdf_text(self, file_bytes: bytes) -> str:
        try:
            pdf_file = BytesIO(file_bytes)
            pdf_reader = pypdf.PdfReader(pdf_file)

            if len(pdf_reader.pages) == 0:
                raise ValueError("PDF contains no pages")

            # Extract metadata for context
            metadata = pdf_reader.metadata
            text_parts = []

            if metadata:
                if metadata.get("/Title"):
                    text_parts.append(f"Title: {metadata['/Title']}\n")
                if metadata.get("/Author"):
                    text_parts.append(f"Author: {metadata['/Author']}\n")
                if metadata.get("/Subject"):
                    text_parts.append(f"Subject: {metadata['/Subject']}\n")
                text_parts.append("\n")

            # Extract text from each page with clear separators
            for page_num, page in enumerate(pdf_reader.pages, 1):
                page_text = page.extract_text()

                if page_text and page_text.strip():
                    # Clean up common PDF artifacts
                    page_text = self._clean_pdf_text(page_text)
                    text_parts.append(f"--- Page {page_num} ---\n")
                    text_parts.append(page_text)
                    text_parts.append("\n\n")

            full_text = "".join(text_parts).strip()

            if not full_text:
                raise ValueError("No extractable text found in PDF")

            return full_text

        except Exception as e:
            raise ValueError(f"Failed to parse PDF: {str(e)}") from e

    def _clean_pdf_text(self, text: str) -> str:
        """
        Clean common PDF text extraction artifacts for better LLM processing.

        Args:
            text: Raw extracted text

        Returns:
            Cleaned text
        """

        # Remove excessive whitespace while preserving paragraph breaks
        text = re.sub(r" +", " ", text)  # Multiple spaces to single space
        text = re.sub(r"\n ", "\n", text)  # Remove leading spaces on lines
        text = re.sub(r" \n", "\n", text)  # Remove trailing spaces on lines
        text = re.sub(r"\n{3,}", "\n\n", text)  # Max 2 consecutive newlines

        # Fix common hyphenation issues at line breaks
        text = re.sub(r"(\w+)-\n(\w+)", r"\1\2", text)

        # Remove form feed characters
        text = text.replace("\f", "\n")

        return text.strip()

    def write(self, path: str, content: str | bytes) -> WriteResult:
        """Write file to container using Docker put_archive API.

        This method uses Docker's put_archive() instead of heredoc to handle
        large files and special characters reliably.

        Args:
            path: Absolute path where the file should be written.
            content: File content as string or bytes.

        Returns:
            WriteResult with path on success, or error message on failure.
        """
        self._ensure_container()
        assert self._container is not None

        try:
            # Parse path into directory and filename
            posix_path = PurePosixPath(path)
            parent_dir = str(posix_path.parent)
            filename = posix_path.name

            # Ensure parent directory exists
            safe_parent_dir = shlex.quote(parent_dir)
            mkdir_result = self.execute(f"mkdir -p {safe_parent_dir}")
            if mkdir_result.exit_code != 0:
                return WriteResult(error=f"Failed to create directory: {mkdir_result.output}")

            # Create tar archive in memory
            content = content if isinstance(content, bytes) else content.encode()
            tar_buffer = io.BytesIO()

            with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
                # Create TarInfo for the file
                tarinfo = tarfile.TarInfo(name=filename)
                tarinfo.size = len(content)
                tarinfo.mtime = int(time.time())
                tarinfo.mode = 0o644

                # Add file to archive
                tar.addfile(tarinfo, io.BytesIO(content))

            # Reset buffer position
            tar_buffer.seek(0)

            # Upload to container
            self._container.put_archive(parent_dir, tar_buffer)

            return WriteResult(path=path)

        except Exception as e:
            return WriteResult(error=f"Failed to write file: {e}")

    def start(self) -> None:
        """Explicitly start the container.

        This is useful for pre-warming containers before use.
        The container is normally started lazily on first operation.
        """
        self._ensure_container()

    def is_alive(self) -> bool:
        """Check if container is running.

        Returns:
            True if container is running, False otherwise.
        """
        if self._container is None:
            return False
        try:
            self._container.reload()
            return self._container.status == "running"
        except Exception:
            return False

    def stop(self) -> None:
        """Stop and remove the container."""
        import contextlib

        if self._container:
            with contextlib.suppress(Exception):
                self._container.stop()
            self._container = None

    def __del__(self) -> None:
        """Cleanup container on deletion."""
        self.stop()


class LocalSandbox(BaseSandbox):  # pragma: no cover
    """Local sandbox using subprocess (no isolation).

    WARNING: This sandbox executes commands directly on the host system
    without isolation. Use DockerSandbox for production workloads.
    """

    def __init__(
        self,
        work_dir: str = "/tmp/pydantic-deep-sandbox",
        sandbox_id: str | None = None,
    ):
        """Initialize local sandbox.

        Args:
            work_dir: Working directory for commands.
            sandbox_id: Unique identifier for this sandbox.
        """
        super().__init__(sandbox_id)
        self._work_dir = work_dir

        # Create work directory
        import os

        os.makedirs(work_dir, exist_ok=True)

    def execute(self, command: str, timeout: int | None = None) -> ExecuteResponse:
        """Execute command using subprocess."""
        import subprocess

        try:
            result = subprocess.run(
                ["sh", "-c", command],
                cwd=self._work_dir,
                capture_output=True,
                text=True,
                timeout=timeout or 120,
            )

            output = result.stdout + result.stderr

            # Truncate if too long
            max_output = 100000
            truncated = len(output) > max_output
            if truncated:
                output = output[:max_output]

            return ExecuteResponse(
                output=output,
                exit_code=result.returncode,
                truncated=truncated,
            )
        except subprocess.TimeoutExpired:
            return ExecuteResponse(
                output="Error: Command timed out",
                exit_code=124,
                truncated=False,
            )
        except Exception as e:
            return ExecuteResponse(
                output=f"Error: {e}",
                exit_code=1,
                truncated=False,
            )
