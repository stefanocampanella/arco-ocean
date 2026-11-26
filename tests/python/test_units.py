# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
"""The systemd user units (systemd/), their installer (scripts/install_units.sh) and the
collection's alerts (scripts/alert.sh), with stand-ins for systemctl, loginctl, gh and the
`arco-ocean` command that record their calls."""

import os
import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).parents[2]
UNITS = sorted((ROOT / "systemd").iterdir())

# Records its arguments, one call per line, and what it reads from a --body-file - in
# $CALLS.body; gh answers FAKE_ISSUE to the issue list (fails with FAKE_GH_FAIL); the token it
# sees goes to $CALLS.env.
RECORDER = """#!/usr/bin/env bash
echo "$(basename "$0") $*" >> "${CALLS}"
if [[ "$(basename "$0")" == loginctl ]]; then echo "${FAKE_LINGER:-no}"; fi
if [[ "$(basename "$0")" == gh && -n "${FAKE_GH_FAIL:-}" ]]; then exit 1; fi
if [[ "$(basename "$0")" == gh && "$*" == "issue list "* ]]; then printf "%b" "${FAKE_ISSUE:-}"; fi
if [[ "$(basename "$0")" == gh && "$*" == *"--body-file -"* ]]; then cat >> "${CALLS}.body"; fi
if [[ "$(basename "$0")" == gh && -n "${GH_TOKEN:-}" ]]; then echo "token ${GH_TOKEN}" >> "${CALLS}.env"; fi
exit 0
"""

# The `arco-ocean` command, for the heartbeat's summary.
FAKE_CLI = """#!/usr/bin/env bash
echo "arco-ocean $*" >> "${CALLS}"
echo "**Collection finished.** The heartbeat's summary."
"""

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="systemd units: Linux only")


@pytest.fixture
def fake(tmp_path: pathlib.Path) -> dict[str, str]:
  bin_dir = tmp_path / "bin"
  bin_dir.mkdir()
  for name in ("systemctl", "loginctl", "gh"):
    (bin_dir / name).write_text(RECORDER)
    (bin_dir / name).chmod(0o755)
  (bin_dir / "arco-ocean").write_text(FAKE_CLI)
  (bin_dir / "arco-ocean").chmod(0o755)
  return {
    "PATH": f"{bin_dir}:/usr/bin:/bin",
    "HOME": str(tmp_path / "home"),
    "XDG_CONFIG_HOME": str(tmp_path / "config"),
    "USER": "someone",
    "CALLS": str(tmp_path / "calls"),
    "ARCO_OCEAN_CLI": str(bin_dir / "arco-ocean"),
  }


def run(script: str, env: dict[str, str], *args: str, cwd=None) -> subprocess.CompletedProcess:
  return subprocess.run(
    ["bash", str(ROOT / "scripts" / script), *args],
    env=env,
    capture_output=True,
    text=True,
    cwd=cwd,
  )


def calls(env: dict[str, str]) -> list[str]:
  path = pathlib.Path(env["CALLS"])
  return path.read_text().splitlines() if path.exists() else []


def unit_dir(env: dict[str, str]) -> pathlib.Path:
  return pathlib.Path(env["XDG_CONFIG_HOME"]) / "systemd" / "user"


def test_units_carry_no_machine_paths():
  # The machine's part (checkout, options) goes into drop-ins, written at install.
  for unit in UNITS:
    text = unit.read_text()
    assert "/home/" not in text and "/data/" not in text, unit.name
  service = (ROOT / "systemd" / "arco-ocean-forecast.service").read_text()
  assert "scripts/forecast.sh --status-url s3://ogs-arco-ocean/status/forecast.json" in service


@pytest.mark.skipif(shutil.which("systemd-analyze") is None, reason="needs systemd-analyze")
def test_units_verify(tmp_path: pathlib.Path):
  # systemd's own check of the units (syntax, settings, the commands they run); the template as
  # its two instances.
  names = []
  for unit in UNITS:
    if unit.name == "arco-ocean-alert@.service":
      for event in ("failed", "finished"):
        shutil.copy(unit, tmp_path / f"arco-ocean-alert@{event}.service")
        names.append(f"arco-ocean-alert@{event}.service")
    else:
      shutil.copy(unit, tmp_path / unit.name)
      names.append(unit.name)
  result = subprocess.run(
    ["systemd-analyze", "--user", "verify", *(str(tmp_path / name) for name in names)],
    capture_output=True,
    text=True,
    cwd=tmp_path,
  )
  assert result.returncode == 0, result.stderr
  calendar = subprocess.run(
    ["systemd-analyze", "calendar", "*-*-* 12:00:00 UTC"], capture_output=True, text=True
  )
  assert calendar.returncode == 0 and "12:00:00 UTC" in calendar.stdout


def test_install_links_the_units_and_writes_the_drop_ins(fake: dict[str, str]):
  result = run("install_units.sh", fake, "--alerts", "--", "--image", "a%b.sif")
  assert result.returncode == 0, result.stderr
  assert "sudo loginctl enable-linger someone" in result.stdout
  forecast = (unit_dir(fake) / "arco-ocean-forecast.service.d" / "local.conf").read_text()
  assert f"WorkingDirectory={ROOT}\n" in forecast
  # % doubled: systemd would read it as a specifier.
  assert 'Environment="FORECAST_OPTIONS=--image a%%b.sif"' in forecast
  # The collection's outcome starts its alert.
  assert "[Unit]\nOnFailure=arco-ocean-alert@failed.service\n" in forecast
  assert "OnSuccess=arco-ocean-alert@finished.service\n" in forecast
  alert = (unit_dir(fake) / "arco-ocean-alert@.service.d" / "local.conf").read_text()
  assert f"WorkingDirectory={ROOT}\n" in alert
  # The heartbeat's state file where forecast.sh writes it, whatever the directory systemd starts in.
  assert f'Environment="ALERT_OPTIONS=--state-file {ROOT}/logs/forecast/status.json"' in alert
  made = calls(fake)
  assert (
    f"systemctl --user link {ROOT}/systemd/arco-ocean-forecast.service"
    f" {ROOT}/systemd/arco-ocean-forecast.timer" in made
  )
  assert f"systemctl --user link {ROOT}/systemd/arco-ocean-alert@.service" in made
  assert "systemctl --user enable --now arco-ocean-forecast.timer" in made
  assert made.index("systemctl --user daemon-reload") < made.index(
    "systemctl --user enable --now arco-ocean-forecast.timer"
  )


def test_install_alert_options(fake: dict[str, str]):
  result = run(
    "install_units.sh", fake, "--alerts", "--alert-repo", "someone/arco-ocean",
    "--", "--log-dir", "/var/forecast",
  )  # fmt: skip
  assert result.returncode == 0, result.stderr
  alert = (unit_dir(fake) / "arco-ocean-alert@.service.d" / "local.conf").read_text()
  # The alert reads the heartbeat where the collection writes it.
  assert (
    'Environment="ALERT_OPTIONS=--repo someone/arco-ocean --state-file /var/forecast/status.json"'
    in alert
  )
  relative = run("install_units.sh", fake, "--alerts", "--", "--project-dir", "elsewhere")
  assert relative.returncode == 0, relative.stderr
  alert = (unit_dir(fake) / "arco-ocean-alert@.service.d" / "local.conf").read_text()
  assert f"--state-file {ROOT}/elsewhere/logs/forecast/status.json" in alert
  bad = run("install_units.sh", fake, "--alerts", "--alert-repo", "a b")
  assert bad.returncode == 1 and "takes OWNER/REPO" in bad.stderr
  alone = run("install_units.sh", fake, "--alert-repo", "someone/arco-ocean")
  assert alone.returncode == 1 and "goes with --alerts" in alone.stderr


def test_install_without_alerts_or_start(fake: dict[str, str]):
  assert run("install_units.sh", fake, "--alerts").returncode == 0
  (unit_dir(fake) / "arco-ocean-alert@.service").symlink_to(
    ROOT / "systemd/arco-ocean-alert@.service"
  )
  result = run("install_units.sh", fake, "--no-start")
  assert result.returncode == 0, result.stderr
  assert "without alerts" in result.stdout
  made = calls(fake)
  assert "systemctl --user enable arco-ocean-forecast.timer" in made
  drop_in = (unit_dir(fake) / "arco-ocean-forecast.service.d" / "local.conf").read_text()
  assert 'Environment="FORECAST_OPTIONS="' in drop_in and "OnFailure" not in drop_in
  # The alerts installed before are gone.
  assert not (unit_dir(fake) / "arco-ocean-alert@.service").is_symlink()
  assert not (unit_dir(fake) / "arco-ocean-alert@.service.d").exists()


def test_install_removes_the_keepalive_of_before(fake: dict[str, str], tmp_path):
  # The GitHub watchdog's keepalive, installed until 26 Nov 2026: its files left the checkout.
  units = unit_dir(fake)
  (units / "arco-ocean-watchdog-keepalive.service.d").mkdir(parents=True)
  (units / "arco-ocean-watchdog-keepalive.service.d" / "local.conf").write_text("[Service]\n")
  for unit in ("service", "timer"):
    (units / f"arco-ocean-watchdog-keepalive.{unit}").symlink_to(tmp_path / f"gone.{unit}")
  result = run("install_units.sh", fake)
  assert result.returncode == 0, result.stderr
  assert "Removed the watchdog's keepalive" in result.stdout
  assert not any(path.name.startswith("arco-ocean-watchdog") for path in units.iterdir())
  assert "systemctl --user disable --now arco-ocean-watchdog-keepalive.timer" in calls(fake)


def test_a_refused_install_removes_nothing(fake: dict[str, str], tmp_path):
  units = unit_dir(fake)
  units.mkdir(parents=True)
  (units / "arco-ocean-watchdog-keepalive.service").symlink_to(tmp_path / "gone.service")
  result = run("install_units.sh", fake, "--alerts", "--alert-repo", "a b")
  assert result.returncode == 1
  assert (units / "arco-ocean-watchdog-keepalive.service").is_symlink() and calls(fake) == []


def test_install_lingering_needs_no_advice(fake: dict[str, str]):
  result = run("install_units.sh", fake | {"FAKE_LINGER": "yes"})
  assert result.returncode == 0 and "enable-linger" not in result.stdout


@pytest.mark.parametrize("option", ["a b", 'a"b', "a'b", "a\\b", "$HOME"])
def test_install_refuses_options_systemd_would_split_or_expand(fake: dict[str, str], option):
  result = run("install_units.sh", fake, "--", "--env-file", option)
  assert result.returncode == 1 and "Error: option" in result.stderr
  assert calls(fake) == []


def test_install_options_go_after_the_separator(fake: dict[str, str]):
  result = run("install_units.sh", fake, "--image", "x.sif")
  assert result.returncode == 1 and "go after --" in result.stderr


def test_uninstall_removes_the_links_and_drop_ins(fake: dict[str, str]):
  assert run("install_units.sh", fake, "--alerts").returncode == 0
  units = unit_dir(fake)
  # What systemctl --user link would have made.
  for name in ("arco-ocean-forecast.service", "arco-ocean-alert@.service"):
    (units / name).symlink_to(ROOT / "systemd" / name)
  (units / "unrelated.service").write_text("")
  # A drop-in of the user's own (systemctl --user edit) stays.
  (units / "arco-ocean-forecast.service.d" / "override.conf").write_text("[Service]\n")
  result = run("install_units.sh", fake, "--uninstall")
  assert result.returncode == 0, result.stderr
  assert sorted(path.name for path in units.iterdir()) == [
    "arco-ocean-forecast.service.d",
    "unrelated.service",
  ]
  assert [path.name for path in (units / "arco-ocean-forecast.service.d").iterdir()] == [
    "override.conf"
  ]
  made = calls(fake)
  assert "systemctl --user disable --now arco-ocean-forecast.timer" in made
  # A collection running is stopped too.
  assert "systemctl --user stop arco-ocean-forecast.service" in made
  # The alerts go first: a collection stopped fails its unit, which would report it.
  assert made.index("systemctl --user stop arco-ocean-alert@*.service") < made.index(
    "systemctl --user stop arco-ocean-forecast.service"
  )


def test_install_from_another_checkout_moves_the_units(fake: dict[str, str], tmp_path):
  units = unit_dir(fake)
  units.mkdir(parents=True)
  old = tmp_path / "old-checkout" / "arco-ocean-forecast.service"
  old.parent.mkdir()
  old.write_text("")
  (units / "arco-ocean-forecast.service").symlink_to(old)
  result = run("install_units.sh", fake)
  assert result.returncode == 0, result.stderr
  # The old link is gone (systemctl link, a stand-in here, would make the new one).
  assert not (units / "arco-ocean-forecast.service").is_symlink()
  made = calls(fake)
  assert made.index("systemctl --user disable arco-ocean-forecast.timer") < made.index(
    f"systemctl --user link {ROOT}/systemd/arco-ocean-forecast.service"
    f" {ROOT}/systemd/arco-ocean-forecast.timer"
  )


def test_install_refuses_to_replace_a_unit_file_of_its_own(fake: dict[str, str]):
  units = unit_dir(fake)
  units.mkdir(parents=True)
  (units / "arco-ocean-forecast.timer").write_text("[Timer]\n")
  result = run("install_units.sh", fake)
  assert result.returncode == 1 and "a file of its own" in result.stderr
  assert (units / "arco-ocean-forecast.timer").read_text() == "[Timer]\n"


@pytest.fixture
def token(fake: dict[str, str]) -> pathlib.Path:
  path = pathlib.Path(fake["XDG_CONFIG_HOME"]) / "arco-ocean" / "github-token"
  path.parent.mkdir(parents=True)
  path.write_text("not-a-real-token")
  path.chmod(0o600)
  return path


# What systemd gives an OnFailure= unit.
MONITOR = {
  "MONITOR_SERVICE_RESULT": "exit-code",
  "MONITOR_EXIT_CODE": "exited",
  "MONITOR_EXIT_STATUS": "1",
  "MONITOR_INVOCATION_ID": "0123abcd",
}


def body(env: dict[str, str]) -> str:
  return pathlib.Path(env["CALLS"] + ".body").read_text()


def test_a_failure_opens_an_issue(fake: dict[str, str], token: pathlib.Path, tmp_path):
  state = tmp_path / "logs" / "status.json"
  state.parent.mkdir()
  state.write_text("{}")
  result = run("alert.sh", fake | MONITOR, "--state-file", str(state), "failed")
  assert result.returncode == 0, result.stderr
  made = calls(fake)
  repo = "--repo stefanocampanella/arco-ocean"
  assert made[0] == (
    f"gh issue list {repo} --label forecast-alert --state open --limit 100 --json number"
    " --jq sort_by(.number) | .[].number"
  )
  assert f"arco-ocean status --state-file {state} summary" in made
  assert any(call.startswith(f"gh label create forecast-alert {repo}") for call in made)
  assert made[-1] == (
    f"gh issue create {repo} --label forecast-alert --title Forecast collection failed"
    " --body-file -"
  )
  text = body(fake)
  assert "A download failed, or the heartbeat could not be checked." in text
  assert "systemd's result `exit-code`, exit `exited` `1`" in text
  assert "The heartbeat's summary." in text
  assert "_SYSTEMD_INVOCATION_ID=0123abcd" in text
  # No path of the machine: the issue is public.
  assert str(tmp_path) not in text
  # The token reaches gh through its environment, never its arguments or the output.
  assert all("not-a-real-token" not in call for call in made)
  assert "not-a-real-token" not in result.stdout + result.stderr + text
  assert pathlib.Path(fake["CALLS"] + ".env").read_text().splitlines()[0] == (
    "token not-a-real-token"
  )


def test_a_failure_with_an_open_issue_comments_on_it(fake: dict[str, str], token: pathlib.Path):
  # Values systemd would not give are kept to the characters its own have.
  odd = MONITOR | {"MONITOR_EXIT_STATUS": "1`@x <y>"}
  result = run(
    "alert.sh", fake | odd | {"FAKE_ISSUE": "7"}, "--state-file", "/nowhere/status.json", "failed"
  )
  assert result.returncode == 0, result.stderr
  made = calls(fake)
  assert made[-1] == "gh issue comment 7 --repo stefanocampanella/arco-ocean --body-file -"
  assert not any("issue create" in call for call in made)
  assert "exit `exited` `1xy`" in body(fake)
  # Without a state file, the summary says so.
  assert "The heartbeat's state could not be read." in body(fake)


def test_a_collection_behind_says_so(fake: dict[str, str], token: pathlib.Path):
  result = run("alert.sh", fake | MONITOR | {"MONITOR_EXIT_STATUS": "3"}, "failed")
  assert result.returncode == 0, result.stderr
  assert "The collection finished behind: a source may have stopped publishing" in body(fake)


def test_a_success_closes_the_open_issues(fake: dict[str, str], token: pathlib.Path):
  # Two open: one opened by hand with the label, say.
  result = run("alert.sh", fake | {"FAKE_ISSUE": "3\\n7"}, "--repo", "someone/x", "finished")
  assert result.returncode == 0, result.stderr
  closes = [call for call in calls(fake) if call.startswith("gh issue close")]
  assert [call.split()[3] for call in closes] == ["3", "7"]
  assert closes[0].startswith("gh issue close 3 --repo someone/x --comment Recovered: a collection")
  # Nothing open: nothing to do.
  pathlib.Path(fake["CALLS"]).unlink()
  quiet = run("alert.sh", fake, "finished")
  assert quiet.returncode == 0 and "nothing to close" in quiet.stdout
  assert len(calls(fake)) == 1


@pytest.mark.parametrize(
  ("args", "said"),
  [([], "give the event"), (["failed", "finished"], "one event only"), (["done"], "unrecognized")],
)
def test_alert_needs_one_event(fake: dict[str, str], token: pathlib.Path, args, said):
  result = run("alert.sh", fake, *args)
  assert result.returncode == 1 and said in result.stderr
  assert calls(fake) == []


def test_alert_needs_a_private_token_file(fake: dict[str, str], token: pathlib.Path):
  token.chmod(0o644)
  result = run("alert.sh", fake, "failed")
  assert result.returncode == 1 and "readable by others" in result.stderr
  missing = run("alert.sh", fake, "--token-file", str(token) + ".missing", "failed")
  assert missing.returncode == 1 and "no token file" in missing.stderr
  # Empty, gh would use its own login instead.
  token.chmod(0o600)
  token.write_text("\n")
  empty = run("alert.sh", fake, "failed")
  assert empty.returncode == 1 and "is empty" in empty.stderr
  assert calls(fake) == []


def test_a_report_github_refuses_is_tried_again(fake: dict[str, str], token: pathlib.Path):
  result = run(
    "alert.sh", fake | MONITOR | {"FAKE_GH_FAIL": "1"}, "--attempts", "3", "--retry-delay", "0",
    "failed",
  )  # fmt: skip
  assert result.returncode == 1 and "the report failed 3 times" in result.stderr
  assert [call.split()[:3] for call in calls(fake)] == [["gh", "issue", "list"]] * 3
  bad = run("alert.sh", fake, "--attempts", "0", "failed")
  assert bad.returncode == 1 and "--attempts takes a positive number" in bad.stderr


def test_alert_follows_a_linked_token_file(fake: dict[str, str], token: pathlib.Path):
  link = token.with_name("linked-token")
  link.symlink_to(token)
  result = run("alert.sh", fake, "--token-file", str(link), "finished")
  assert result.returncode == 0, result.stderr


def test_scripts_are_executable():
  for name in ("install_units.sh", "alert.sh"):
    assert os.access(ROOT / "scripts" / name, os.X_OK), name
