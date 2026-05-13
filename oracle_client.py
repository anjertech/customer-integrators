#!/usr/bin/env python3
"""Oracle Instant Client bootstrap for legacy databases that require thick mode."""

import os
from pathlib import Path
from typing import List, Sequence, Tuple

import oracledb


ENV_VAR_CANDIDATES: Sequence[str] = (
    "PRESA_ORACLE_CLIENT_DIR",
    "ORACLE_CLIENT_DIR",
)

RELATIVE_DIR_CANDIDATES: Sequence[str] = (
    "instantclient",
    "instantclient_23_3",
    "vendor/oracle/instantclient",
    "vendor/oracle/instantclient_23_3",
    ".oracle/instantclient",
    ".oracle/instantclient_23_3",
)


def _unique_candidates(candidates: Sequence[Tuple[Path, bool]]) -> List[Tuple[Path, bool]]:
    unique: List[Tuple[Path, bool]] = []
    seen = set()

    for path, explicit in candidates:
        normalized = str(path.expanduser())
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append((Path(normalized), explicit))

    return unique


def get_oracle_client_candidates() -> List[Tuple[Path, bool]]:
    base_dir = Path(__file__).resolve().parent
    candidates: List[Tuple[Path, bool]] = []

    for env_var in ENV_VAR_CANDIDATES:
        value = os.environ.get(env_var)
        if value:
            candidates.append((Path(value).expanduser(), True))

    for relative_dir in RELATIVE_DIR_CANDIDATES:
        candidates.append((base_dir / relative_dir, False))

    return _unique_candidates(candidates)


def initialize_oracle_thick_mode() -> str:
    if not oracledb.is_thin_mode():
        return "already initialized"

    candidates = get_oracle_client_candidates()
    checked_paths: List[str] = []
    errors: List[str] = []

    for candidate_path, explicit in candidates:
        path_text = str(candidate_path)
        if explicit or candidate_path.is_dir():
            checked_paths.append(path_text)
        else:
            continue

        try:
            oracledb.init_oracle_client(lib_dir=path_text)
            return path_text
        except Exception as exc:
            errors.append(f"{path_text}: {exc}")

    message_lines = [
        "Unable to initialize python-oracledb thick mode.",
        "These GMUni scripts cannot use thin mode against this Oracle server version (DPY-3010).",
        "Set PRESA_ORACLE_CLIENT_DIR or ORACLE_CLIENT_DIR to an accessible Oracle Instant Client directory,",
        "or place Instant Client in one of these project paths:",
    ]
    message_lines.extend(f"  - {Path(__file__).resolve().parent / relative_dir}" for relative_dir in RELATIVE_DIR_CANDIDATES)

    if checked_paths:
        message_lines.append("Tried these client directories:")
        message_lines.extend(f"  - {path}" for path in checked_paths)
    else:
        message_lines.append("No accessible Instant Client directory was found.")

    if errors:
        message_lines.append("Initialization errors:")
        message_lines.extend(f"  - {error}" for error in errors)

    message_lines.append(
        "If you are running inside the Codex sandbox, avoid ~/Downloads because the sandbox cannot open that path."
    )

    raise RuntimeError("\n".join(message_lines))
