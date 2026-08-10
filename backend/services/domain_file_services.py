"""Domain-specific :class:`FileService` subclasses.

Each module owns the policy that distinguishes one root from the
others:

* :class:`ConfigFileService` — ``machine_config/profiles``. The
  operator can CRUD files and folders. The legacy
  The legacy flat-file contract (pre-issue #49) only saw the top-level
  ``.cfg`` files, so the listing filter matches that.
* :class:`ProgramFileService` — ``nc_files/``. Stores G-code files
  (``.gcode`` / ``.ngc``) and exposes a small binary-write entry
  point for the upload endpoint.
* :class:`StagedFileService` — ``machine_config/ready_for_deploy``.
  Read-only by default after a compile step flips the POSIX write
  bits; the deploy step clears and rewrites the active root.
* :class:`ActiveFileService` — ``machine_config/active``. Read-only
  viewer for the currently running payload. Exposes the
  machine-name probe that the Active dashboard uses for its
  "currently running machine" header.

The four services are also responsible for the legacy directory
bootstrap (creating the roots on first boot) — the previous
``modules.machineconfig.filesystem.ensure_directories`` helper is
folded into the service constructors.
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import List, Optional

from .file_service import FileMetadata, FileService

logger = logging.getLogger("backend.services.domain_file_services")


# ---------------------------------------------------------------------- #
# Shared paths                                                            #
# ---------------------------------------------------------------------- #

#: Backend root = ``<repo>/backend``.  Module-local paths are computed
#: relative to this anchor so the four roots live next to the source.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = _BACKEND_ROOT.parent
_MACHINE_CONFIG_DIR = _PROJECT_ROOT / "machine_config"
_PROFILES_DIR = _MACHINE_CONFIG_DIR / "profiles"
_STAGED_DIR = _MACHINE_CONFIG_DIR / "ready_for_deploy"
_ACTIVE_DIR = _MACHINE_CONFIG_DIR / "active"
_NC_FILES_DIR = _PROJECT_ROOT / "nc_files"
#: LinuxCNC's ``[RS274NGC]USER_M_PATH``. Custom M-codes (M100..M199)
#: drop in here as bare ``M<num>`` files; the interpreter expands
#: ``M<num>`` MDI calls into the file's content. Lives next to
#: ``machine_config/profiles/`` and is therefore reachable through
#: the machineconfig router the same way profile content is.
_M_CODES_DIR = _MACHINE_CONFIG_DIR / "m_codes"


# ---------------------------------------------------------------------- #
# ConfigFileService                                                       #
# ---------------------------------------------------------------------- #


class ConfigFileService(FileService):
    """Manages ``machine_config/profiles/``.

    The default ``file_service`` listing walks the full tree
    recursively. The legacy ``/api/v1/config`` endpoint only
    exposed the top-level ``.cfg`` files, so the ``filename_filter``
    keeps that surface source-compatible while the new
    ``/api/v1/modules/machineconfig/profiles/tree`` endpoint
    consumes the unfiltered walk.
    """

    default_read_only = False

    @staticmethod
    def cfg_filter(name: str) -> bool:
        return name.lower().endswith(".cfg")

    def __init__(self, root: Optional[Path] = None) -> None:
        super().__init__(root or _PROFILES_DIR)


# ---------------------------------------------------------------------- #
# MCodeFileService                                                         #
# ---------------------------------------------------------------------- #


class MCodeFileService(FileService):
    """Manages LinuxCNC custom M-codes in ``machine_config/m_codes/``.

    Custom M-codes are dispatched by the interpreter when an operator
    issues the matching ``M<num>`` MDI command. The convention is a
    bare file ``M100`` (no extension) at :data:`_M_CODES_DIR`; the
    filesystem layout mirrors what the upstream LinuxCNC docs
    describe (the ``[RS274NGC]USER_M_PATH`` INI variable).

    The class limits accepted names to the canonical range
    ``M100..M199`` (``MCODE_NAME`` regex below). Out-of-range names
    land in the directory but never surface through the listing /
    read endpoints, so an operator can drop anything in there
    without polluting the UI. The strict range keeps the contract
    simple and matches the documented LinuxCNC defaults; widening
    it is a one-line regex change.
    """

    default_read_only = False

    #: LinuxCNC's reserved custom-M-code range. M100..M199 maps to
    #: ``M1\d{2}`` so the regex is intentionally tight.
    MCODE_NAME = re.compile(r"^M1\d{2}$")

    #: Public alias used by the macros router + frontend validator.
    KIND = "mcode"

    @classmethod
    def mcode_filter(cls, name: str) -> bool:
        return bool(cls.MCODE_NAME.match(name))

    def __init__(self, root: Optional[Path] = None) -> None:
        super().__init__(root or _M_CODES_DIR)
        self.filename_filter = self.mcode_filter


# ---------------------------------------------------------------------- #
# ProgramFileService                                                      #
# ---------------------------------------------------------------------- #


class ProgramFileService(FileService):
    """Manages G-code files in ``nc_files/``.

    The class extends :class:`FileService` with a binary write
    helper used by the upload endpoint and a small listing filter
    that drops anything that does not look like a G-code file
    (``.gcode`` / ``.ngc``).
    """

    default_read_only = False

    #: Extensions surfaced by :meth:`list_files`. Matches the
    #: behaviour of the original ``/api/v1/programs`` endpoint.
    ALLOWED_EXTENSIONS = (".gcode", ".ngc")

    @classmethod
    def gcode_filter(cls, name: str) -> bool:
        return name.lower().endswith(cls.ALLOWED_EXTENSIONS)

    def __init__(self, root: Optional[Path] = None) -> None:
        super().__init__(root or _NC_FILES_DIR)
        self.filename_filter = self.gcode_filter

    def save_upload(self, filename: str, data: bytes) -> None:
        """Persist an uploaded G-code payload.

        Used by the upload endpoint; the binary write honours the
        :class:`FileService` read-only policy and the safe-join
        invariant.
        """
        # ``write_bytes`` already does the safe-join + read-only
        # check; this thin wrapper documents intent.
        self.write_bytes(filename, data, overwrite=True)

    def delete_file(self, filename: str) -> None:
        """Delete a single G-code file by basename."""
        # Use the parent ``delete`` method, which honours
        # :meth:`safe_join` for callers passing arbitrary strings.
        self.delete(filename)

    def resolve_program_path(self, filename: str) -> Path:
        """Return the absolute path of ``filename`` for the loader.

        Kept as a separate method because the legacy
        ``load_program`` endpoint needs the resolved ``Path``
        (rather than just the bytes) to hand off to
        ``linuxcnc.execute_sync_cmd`` — that flow is explicitly
        out of scope for this refactor (issue #49).
        """
        return self.safe_join(filename)

    def list_program_files(self) -> List[FileMetadata]:
        """Return only the G-code files, with metadata for the loader."""
        return self.list_files()


# ---------------------------------------------------------------------- #
# StagedFileService                                                       #
# ---------------------------------------------------------------------- #


class StagedFileService(FileService):
    """Manages ``machine_config/ready_for_deploy/``.

    The staged root is treated as a snapshot: after a compile step
    every artifact is flipped read-only (the legacy
    ``mark_staged_readonly`` helper). The router still passes the
    resulting artifacts into :meth:`deploy_to_active`, which is the
    one place that gets to write into the active root.
    """

    default_read_only = True

    def __init__(self, root: Optional[Path] = None) -> None:
        super().__init__(root or _STAGED_DIR)

    def clear_and_stage(self, compiler, source: Path) -> List[Path]:
        """Wipe the staged root and ask ``compiler`` to write fresh artifacts.

        The wrapper centralises the "clear → compile → chmod"
        sequence so the router does not have to know that
        :func:`shutil.rmtree` and :func:`os.chmod` are involved.
        """
        self.clear_directory()
        try:
            artifacts = compiler.compile(source, self.root)
        finally:
            # Even when the compile raises mid-way, mark whatever
            # made it onto disk as a snapshot so a stale half-stage
            # does not become a deploy target.
            self.mark_tree_read_only()
        return list(artifacts)

    def mark_read_only(self) -> int:
        """Re-apply the read-only bits to the whole staged tree."""
        return self.mark_tree_read_only()

    def is_empty(self) -> bool:
        """Return ``True`` when the staging area has no entries."""
        if not self.root.exists():
            return True
        return not any(self.root.iterdir())

    # ------------------------------------------------------------------ #
    # Deploy                                                              #
    # ------------------------------------------------------------------ #

    def deploy_to_active(
        self,
        active_service: "ActiveFileService",
    ) -> List[str]:
        """Promote the staged payload into ``active_service``.

        Returns the basenames of the files copied. The active root
        is cleared first so the deploy is a true promotion (no
        leftover files from a prior active payload).
        """
        if self.is_empty():
            raise FileNotFoundError(
                "Staging area is empty. Compile a profile before deploying."
            )
        active_service.clear_directory()
        return self.copy_tree(self.root, active_service.root)


# ---------------------------------------------------------------------- #
# ActiveFileService                                                       #
# ---------------------------------------------------------------------- #


class ActiveFileService(FileService):
    """Manages ``machine_config/active/``.

    Read-only viewer: the router endpoints list files, return their
    content, and read the current machine name. Writes are
    blocked by the parent's :meth:`write_file` /
    :meth:`delete` checks (the POSIX write bits stay cleared after
    a deploy).
    """

    default_read_only = True

    def __init__(self, root: Optional[Path] = None) -> None:
        super().__init__(root or _ACTIVE_DIR)

    def list_active_files(self) -> List[FileMetadata]:
        """Return only the files (not the directory itself) for the listing."""
        return [entry for entry in self.list_files() if entry.kind == "file"]

    def machine_name(self) -> Optional[str]:
        """Best-effort detection of the current machine name."""
        return self.parse_machine_name()


# ---------------------------------------------------------------------- #
# Service factory helpers                                                  #
# ---------------------------------------------------------------------- #


#: Cached instances keyed by ``str(root)`` so the FastAPI dependency
#: system can hand out a single object per request lifecycle. Tests
#: that need an isolated root should bypass this cache and call
#: the constructor directly with a custom ``root`` argument.
_SERVICE_CACHE: dict[str, FileService] = {}


def _cache_key(cls: type, root: Optional[Path]) -> str:
    return f"{cls.__name__}:{Path(root).resolve() if root else '<default>'}"


def get_config_service(root: Optional[Path] = None) -> ConfigFileService:
    key = _cache_key(ConfigFileService, root)
    service = _SERVICE_CACHE.get(key)
    if service is None:
        service = ConfigFileService(root=root)
        _SERVICE_CACHE[key] = service
    return service


def get_program_service(root: Optional[Path] = None) -> ProgramFileService:
    key = _cache_key(ProgramFileService, root)
    service = _SERVICE_CACHE.get(key)
    if service is None:
        service = ProgramFileService(root=root)
        _SERVICE_CACHE[key] = service
    return service


def get_staged_service(root: Optional[Path] = None) -> StagedFileService:
    key = _cache_key(StagedFileService, root)
    service = _SERVICE_CACHE.get(key)
    if service is None:
        service = StagedFileService(root=root)
        _SERVICE_CACHE[key] = service
    return service


def get_active_service(root: Optional[Path] = None) -> ActiveFileService:
    key = _cache_key(ActiveFileService, root)
    service = _SERVICE_CACHE.get(key)
    if service is None:
        service = ActiveFileService(root=root)
        _SERVICE_CACHE[key] = service
    return service


def get_mcode_service(root: Optional[Path] = None) -> MCodeFileService:
    """Return the cached :class:`MCodeFileService` for the m-codes root.

    Used both by the machineconfig ``/m-codes/...`` router (which the
    universal editor talks to) and by the macros router's
    ``?kind=mcode`` path (which the dashboard + Machine Config UI
    uses). They share a single instance because the underlying
    :class:`FileService` is stateless besides its ``root`` path.
    """
    key = _cache_key(MCodeFileService, root)
    service = _SERVICE_CACHE.get(key)
    if service is None:
        service = MCodeFileService(root=root)
        _SERVICE_CACHE[key] = service
    return service


def reset_service_cache() -> None:
    """Drop the cached service instances.

    Exposed for the test-suite (and for the FastAPI dependency
    teardown) so an isolated test that swaps the underlying
    :data:`_PROFILES_DIR` etc. can pick up a fresh service
    without leaking the old root through the cache.
    """
    _SERVICE_CACHE.clear()


__all__ = [
    "ActiveFileService",
    "ConfigFileService",
    "MCodeFileService",
    "ProgramFileService",
    "StagedFileService",
    "get_active_service",
    "get_config_service",
    "get_mcode_service",
    "get_program_service",
    "get_staged_service",
    "reset_service_cache",
] 
