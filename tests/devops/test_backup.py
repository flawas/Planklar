import os
import re
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")


def test_skripte_ausfuehrbar_und_syntaktisch_korrekt() -> None:
    for name in ("backup.sh", "restore.sh"):
        path = SCRIPTS / name
        assert path.stat().st_mode & stat.S_IXUSR
        subprocess.run(["bash", "-n", str(path)], check=True)


def test_backup_dienst_nur_im_profil_mit_festem_tag() -> None:
    block = COMPOSE.split("  backup:\n", 1)[1].split("\nvolumes:", 1)[0]
    assert 'profiles: ["backup"]' in block
    assert re.search(r"image: amazon/aws-cli:\d", block)


def test_runbook_deckt_pflichtthemen_ab() -> None:
    runbook = (ROOT / "docs" / "runbook.md").read_text(encoding="utf-8")
    for heading in ("## Start", "## Update", "## Backup", "## Restore", "## Rotation von Secrets"):
        assert heading in runbook


def test_backup_ruft_pg_dump_und_s3_sync(tmp_path: Path) -> None:
    """Mit Attrappe für `docker` prüfen, welche Befehle das Skript absetzt."""
    log = tmp_path / "calls.log"
    fake = tmp_path / "bin"
    fake.mkdir()
    docker = fake / "docker"
    docker.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\necho DUMP\n', encoding="utf-8")
    docker.chmod(0o755)
    backups = tmp_path / "backups"
    env = {**os.environ, "PATH": f"{fake}:{os.environ['PATH']}", "BACKUP_DIR": str(backups)}

    subprocess.run([str(SCRIPTS / "backup.sh")], check=True, env=env, capture_output=True)

    calls = log.read_text(encoding="utf-8")
    assert "exec -T db pg_dump -U liquet -Fc liquet" in calls
    assert "s3 sync s3://liquet /backup/s3 --delete" in calls
    dumps = list((backups / "db").glob("liquet-*.dump"))
    assert len(dumps) == 1
    assert not list((backups / "db").glob("*.part"))


def test_restore_ohne_dump_bricht_ab(tmp_path: Path) -> None:
    env = {**os.environ, "BACKUP_DIR": str(tmp_path)}
    res = subprocess.run([str(SCRIPTS / "restore.sh")], env=env, capture_output=True)
    assert res.returncode != 0


def test_keine_zugangsdaten_in_skripten_und_runbook() -> None:
    for path in (*SCRIPTS.glob("*.sh"), ROOT / "docs" / "runbook.md"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"(?i)(password|secret|key)\s*=\s*[^\s$<]{6,}", text), path
