"""Provenance sidecars, round-tripping, and scanning a fabricated workspace."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from lithocloud.core.artifacts import (
    ARTIFACTS_DIRNAME,
    PROVENANCE_NAME,
    Artifact,
    ArtifactError,
    ancestors_of,
    artifact_id_for,
    index_by_id,
    parents_of,
    read_provenance,
    scan_project,
    write_provenance,
)
from lithocloud.core.runs import create_run_dir, finish_run, write_run_manifest

WHEN = dt.datetime(2026, 8, 26, 14, 32)


def make_run(workspace: Path, engine: str, action: str, when: dt.datetime) -> Path:
    run_dir = create_run_dir(workspace, engine, action, when=when)
    write_run_manifest(run_dir, engine=engine, engine_version="1.0.0", action=action)
    return run_dir


def touch(run_dir: Path, name: str, text: str = "data") -> Path:
    path = run_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Ids
# --------------------------------------------------------------------------- #


def test_artifact_id_is_readable_and_derived_from_the_run(tmp_path: Path) -> None:
    run_dir = make_run(tmp_path, "ricp", "register", WHEN)
    assert artifact_id_for(run_dir, "registered") == (
        "2026-08-26_1432_ricp_register__registered"
    )


def test_artifact_ids_are_unique_across_runs_in_the_same_minute(tmp_path: Path) -> None:
    one = make_run(tmp_path, "ricp", "register", WHEN)
    two = make_run(tmp_path, "ricp", "register", WHEN)
    assert artifact_id_for(one, "out") != artifact_id_for(two, "out")


def test_artifact_id_rejects_an_empty_key(tmp_path: Path) -> None:
    run_dir = make_run(tmp_path, "e", "a", WHEN)
    with pytest.raises(ArtifactError, match="empty after sanitising"):
        artifact_id_for(run_dir, "///")


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #


def test_write_provenance_records_every_field(tmp_path: Path) -> None:
    run_dir = make_run(tmp_path, "ricp", "register", WHEN)
    touch(run_dir, "registered.laz")

    artifact = write_provenance(
        run_dir,
        key="registered",
        type="pointcloud",
        files=["registered.laz"],
        engine="ricp",
        engine_version="1.0.0",
        action="register",
        params={"voxel": 0.05},
        inputs=["some_earlier__cloud"],
    )

    assert artifact.artifact_id == "2026-08-26_1432_ricp_register__registered"
    assert artifact.type == "pointcloud"
    assert artifact.files == ("registered.laz",)
    assert artifact.engine == "ricp"
    assert artifact.engine_version == "1.0.0"
    assert artifact.action == "register"
    assert artifact.params == {"voxel": 0.05}
    assert artifact.inputs == ("some_earlier__cloud",)
    assert artifact.created.endswith("Z")


def test_sidecar_lands_in_its_own_folder_and_keeps_its_name(tmp_path: Path) -> None:
    run_dir = make_run(tmp_path, "e", "a", WHEN)
    touch(run_dir, "one.laz")
    touch(run_dir, "two.csv")

    first = write_provenance(run_dir, key="one", type="pointcloud", files=["one.laz"])
    second = write_provenance(run_dir, key="two", type="table", files=["two.csv"])

    assert first.provenance_path is not None and second.provenance_path is not None
    assert first.provenance_path.name == PROVENANCE_NAME
    assert second.provenance_path.name == PROVENANCE_NAME
    assert first.provenance_path != second.provenance_path
    assert first.provenance_path.parent.name == first.artifact_id
    assert first.provenance_path.parent.parent.name == ARTIFACTS_DIRNAME


def test_files_are_stored_relative_so_the_workspace_can_move(tmp_path: Path) -> None:
    run_dir = make_run(tmp_path, "e", "a", WHEN)
    absolute = touch(run_dir, "sub/deep.laz")

    artifact = write_provenance(
        run_dir, key="out", type="pointcloud", files=[absolute]
    )

    assert artifact.files == ("sub/deep.laz",)
    stored = json.loads(artifact.provenance_path.read_text(encoding="utf-8"))
    assert stored["files"] == ["sub/deep.laz"]
    assert str(tmp_path) not in json.dumps(stored)


def test_several_files_in_one_artifact(tmp_path: Path) -> None:
    run_dir = make_run(tmp_path, "e", "a", WHEN)
    touch(run_dir, "cloud.laz")
    touch(run_dir, "cloud.laz.aux")

    artifact = write_provenance(
        run_dir, key="out", type="pointcloud", files=["cloud.laz", "cloud.laz.aux"]
    )
    assert artifact.files == ("cloud.laz", "cloud.laz.aux")


def test_explicit_artifact_id_is_honoured(tmp_path: Path) -> None:
    run_dir = make_run(tmp_path, "e", "a", WHEN)
    touch(run_dir, "f.csv")

    artifact = write_provenance(
        run_dir, artifact_id="my-own-id", type="table", files=["f.csv"]
    )
    assert artifact.artifact_id == "my-own-id"


def test_write_provenance_needs_a_key_or_an_id(tmp_path: Path) -> None:
    run_dir = make_run(tmp_path, "e", "a", WHEN)
    touch(run_dir, "f.csv")
    with pytest.raises(ArtifactError, match="either 'key' or 'artifact_id'"):
        write_provenance(run_dir, type="table", files=["f.csv"])


def test_unknown_artifact_type_is_rejected(tmp_path: Path) -> None:
    run_dir = make_run(tmp_path, "e", "a", WHEN)
    touch(run_dir, "f.obj")
    with pytest.raises(ArtifactError, match="not one of"):
        write_provenance(run_dir, key="out", type="mesh", files=["f.obj"])


def test_a_file_that_does_not_exist_is_rejected(tmp_path: Path) -> None:
    run_dir = make_run(tmp_path, "e", "a", WHEN)
    with pytest.raises(ArtifactError, match="does not exist"):
        write_provenance(run_dir, key="out", type="table", files=["ghost.csv"])


def test_a_file_outside_the_run_folder_is_rejected(tmp_path: Path) -> None:
    run_dir = make_run(tmp_path, "e", "a", WHEN)
    outside = tmp_path / "elsewhere.csv"
    outside.write_text("x", encoding="utf-8")

    with pytest.raises(ArtifactError, match="outside its run folder"):
        write_provenance(run_dir, key="out", type="table", files=[outside])


def test_an_artifact_needs_at_least_one_file(tmp_path: Path) -> None:
    run_dir = make_run(tmp_path, "e", "a", WHEN)
    with pytest.raises(ArtifactError, match="no files given"):
        write_provenance(run_dir, key="out", type="table", files=[])


def test_write_provenance_needs_an_existing_run_folder(tmp_path: Path) -> None:
    with pytest.raises(ArtifactError, match="no such run folder"):
        write_provenance(tmp_path / "nope", key="k", type="table", files=[])


# --------------------------------------------------------------------------- #
# Round-trip
# --------------------------------------------------------------------------- #


def test_round_trip(tmp_path: Path) -> None:
    run_dir = make_run(tmp_path, "condition", "gmm_clustering", WHEN)
    touch(run_dir, "labelled.laz")
    touch(run_dir, "report.md")

    written = write_provenance(
        run_dir,
        key="labelled",
        type="pointcloud",
        files=["labelled.laz", "report.md"],
        engine="condition",
        engine_version="8.3",
        action="gmm_clustering",
        params={"n_components": 5, "seed": 42, "tol": 1e-6},
        inputs=["a__cloud", "b__model"],
    )

    read_back = read_provenance(written.provenance_path)

    assert read_back.artifact_id == written.artifact_id
    assert read_back.type == written.type
    assert read_back.files == written.files
    assert read_back.engine == written.engine
    assert read_back.engine_version == written.engine_version
    assert read_back.action == written.action
    assert read_back.params == written.params
    assert read_back.inputs == written.inputs
    assert read_back.created == written.created
    assert read_back.to_dict() == written.to_dict()


def test_round_trip_preserves_numeric_params_exactly(tmp_path: Path) -> None:
    """Recorded parameters are the reproducibility record - no rounding."""
    run_dir = make_run(tmp_path, "e", "a", WHEN)
    touch(run_dir, "f.csv")
    params = {"tol": 1e-12, "big": 1e18, "ratio": 1 / 3, "neg": -0.0, "n": 7}

    written = write_provenance(
        run_dir, key="out", type="table", files=["f.csv"], params=params
    )
    read_back = read_provenance(written.provenance_path)

    assert read_back.params == params
    assert repr(read_back.params["ratio"]) == repr(params["ratio"])


def test_read_provenance_accepts_the_artifact_folder(tmp_path: Path) -> None:
    run_dir = make_run(tmp_path, "e", "a", WHEN)
    touch(run_dir, "f.csv")
    written = write_provenance(run_dir, key="out", type="table", files=["f.csv"])

    assert read_provenance(written.provenance_path.parent).artifact_id == (
        written.artifact_id
    )


def test_read_provenance_resolves_the_run_folder_and_the_paths(tmp_path: Path) -> None:
    run_dir = make_run(tmp_path, "e", "a", WHEN)
    touch(run_dir, "f.csv")
    written = write_provenance(run_dir, key="out", type="table", files=["f.csv"])

    read_back = read_provenance(written.provenance_path)

    assert read_back.run_dir == run_dir.resolve()
    assert read_back.paths == ((run_dir / "f.csv").resolve(),)
    assert read_back.exists is True
    assert read_back.missing == ()


def test_a_deleted_file_is_reported_as_missing(tmp_path: Path) -> None:
    run_dir = make_run(tmp_path, "e", "a", WHEN)
    touch(run_dir, "f.csv")
    written = write_provenance(run_dir, key="out", type="table", files=["f.csv"])
    (run_dir / "f.csv").unlink()

    read_back = read_provenance(written.provenance_path)
    assert read_back.exists is False
    assert read_back.missing == ((run_dir / "f.csv").resolve(),)


def test_paths_need_a_known_run_dir() -> None:
    artifact = Artifact(artifact_id="x", type="table", files=("f.csv",))
    with pytest.raises(ArtifactError, match="run_dir is unknown"):
        _ = artifact.paths
    assert artifact.exists is False


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"artifact_id": ""}, "non-empty string"),
        ({"type": "mesh"}, "not one of"),
        ({"files": []}, "must not be empty"),
        ({"files": "one.laz"}, "must be a list"),
        ({"files": [""]}, "non-empty strings"),
        ({"inputs": "an-id"}, "must be a list"),
        ({"params": []}, "must be an object"),
        ({"version": 99}, "unsupported provenance version"),
    ],
)
def test_a_corrupt_sidecar_is_rejected(
    tmp_path: Path, mutation: dict, message: str
) -> None:
    run_dir = make_run(tmp_path, "e", "a", WHEN)
    touch(run_dir, "f.csv")
    written = write_provenance(run_dir, key="out", type="table", files=["f.csv"])

    data = json.loads(written.provenance_path.read_text(encoding="utf-8"))
    data.update(mutation)
    written.provenance_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ArtifactError, match=message):
        read_provenance(written.provenance_path)


@pytest.mark.parametrize("key", ["artifact_id", "type", "files"])
def test_a_sidecar_missing_a_required_field_is_rejected(tmp_path: Path, key: str) -> None:
    run_dir = make_run(tmp_path, "e", "a", WHEN)
    touch(run_dir, "f.csv")
    written = write_provenance(run_dir, key="out", type="table", files=["f.csv"])

    data = json.loads(written.provenance_path.read_text(encoding="utf-8"))
    del data[key]
    written.provenance_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ArtifactError, match="missing"):
        read_provenance(written.provenance_path)


def test_missing_sidecar(tmp_path: Path) -> None:
    with pytest.raises(ArtifactError, match="no such provenance file"):
        read_provenance(tmp_path / PROVENANCE_NAME)


def test_unreadable_sidecar(tmp_path: Path) -> None:
    path = tmp_path / PROVENANCE_NAME
    path.write_text("{ truncated", encoding="utf-8")
    with pytest.raises(ArtifactError, match="invalid JSON"):
        read_provenance(path)


# --------------------------------------------------------------------------- #
# Scanning a fabricated workspace
# --------------------------------------------------------------------------- #


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """A fake project: ingest -> register -> condition, plus a failed run.

        raw cloud (not an artifact)
             |
        ingest__canonical  --+
                             |
        register__registered <-- register__transform
             |
        condition__labelled, condition__report
    """
    ws = tmp_path / "Francon"

    ingest = make_run(ws, "tlsphoto", "ingest", dt.datetime(2026, 8, 26, 9, 0))
    touch(ingest, "canonical.laz")
    write_provenance(
        ingest,
        key="canonical",
        type="pointcloud",
        files=["canonical.laz"],
        engine="tlsphoto",
        engine_version="0.5",
        action="ingest",
        params={"crs": "EPSG:2950"},
        inputs=["raw/site.e57"],  # deliberately not an artifact id
        created="2026-08-26T13:00:00Z",
    )
    finish_run(ingest, 0)

    register = make_run(ws, "ricp", "register", dt.datetime(2026, 8, 26, 10, 30))
    touch(register, "registered.laz")
    touch(register, "transform.json")
    write_provenance(
        register,
        key="registered",
        type="pointcloud",
        files=["registered.laz"],
        engine="ricp",
        engine_version="1.0.0",
        action="register",
        inputs=["2026-08-26_0900_tlsphoto_ingest__canonical"],
        created="2026-08-26T14:30:00Z",
    )
    write_provenance(
        register,
        key="transform",
        type="transform",
        files=["transform.json"],
        engine="ricp",
        engine_version="1.0.0",
        action="register",
        inputs=["2026-08-26_0900_tlsphoto_ingest__canonical"],
        created="2026-08-26T14:30:01Z",
    )
    finish_run(register, 0)

    condition = make_run(ws, "condition", "gmm_clustering", dt.datetime(2026, 8, 26, 11, 0))
    touch(condition, "labelled.laz")
    touch(condition, "report.md")
    write_provenance(
        condition,
        key="labelled",
        type="pointcloud",
        files=["labelled.laz"],
        engine="condition",
        engine_version="8.3",
        action="gmm_clustering",
        inputs=["2026-08-26_1030_ricp_register__registered"],
        created="2026-08-26T15:00:00Z",
    )
    write_provenance(
        condition,
        key="report",
        type="report",
        files=["report.md"],
        engine="condition",
        engine_version="8.3",
        action="gmm_clustering",
        inputs=["2026-08-26_1030_ricp_register__registered"],
        created="2026-08-26T15:00:01Z",
    )
    finish_run(condition, 0)

    # A run that crashed: it wrote a file and even a sidecar, but no _DONE.json.
    failed = make_run(ws, "preprocess", "vegetation", dt.datetime(2026, 8, 26, 12, 0))
    touch(failed, "half.laz")
    write_provenance(
        failed,
        key="cleaned",
        type="pointcloud",
        files=["half.laz"],
        engine="preprocess",
        engine_version="0.1",
        action="vegetation",
        created="2026-08-26T16:00:00Z",
    )
    finish_run(failed, 1)

    return ws


def test_scan_finds_every_artifact_of_finished_runs(workspace: Path) -> None:
    ids = [a.artifact_id for a in scan_project(workspace)]

    assert ids == [
        "2026-08-26_0900_tlsphoto_ingest__canonical",
        "2026-08-26_1030_ricp_register__registered",
        "2026-08-26_1030_ricp_register__transform",
        "2026-08-26_1100_condition_gmm_clustering__labelled",
        "2026-08-26_1100_condition_gmm_clustering__report",
    ]


def test_scan_skips_runs_that_did_not_finish(workspace: Path) -> None:
    """A crashed run must not contribute artifacts - that is what _DONE is for."""
    ids = [a.artifact_id for a in scan_project(workspace)]
    assert not any("preprocess" in i for i in ids)

    with_unfinished = [a.artifact_id for a in scan_project(workspace, include_unfinished=True)]
    assert any("preprocess" in i for i in with_unfinished)
    assert len(with_unfinished) == len(ids) + 1


def test_scan_is_sorted_by_creation_time(workspace: Path) -> None:
    created = [a.created for a in scan_project(workspace)]
    assert created == sorted(created)


def test_scan_keeps_types_and_lineage(workspace: Path) -> None:
    by_id = index_by_id(scan_project(workspace))

    registered = by_id["2026-08-26_1030_ricp_register__registered"]
    assert registered.type == "pointcloud"
    assert registered.engine == "ricp"
    assert registered.engine_version == "1.0.0"
    assert registered.inputs == ("2026-08-26_0900_tlsphoto_ingest__canonical",)


def test_scan_resolves_files_that_are_really_there(workspace: Path) -> None:
    for artifact in scan_project(workspace):
        assert artifact.exists, artifact.artifact_id


def test_scan_on_an_empty_or_missing_workspace(tmp_path: Path) -> None:
    assert scan_project(tmp_path) == []
    assert scan_project(tmp_path / "nope") == []


def test_scan_skips_a_corrupt_sidecar_without_losing_the_others(
    workspace: Path,
) -> None:
    """The project tree must always open, however damaged a sidecar is."""
    good = scan_project(workspace)
    victim = good[0].provenance_path
    victim.write_text("{ truncated", encoding="utf-8")

    survivors = scan_project(workspace)

    assert len(survivors) == len(good) - 1
    assert good[0].artifact_id not in [a.artifact_id for a in survivors]


def test_scan_ignores_a_stray_folder_without_a_sidecar(workspace: Path) -> None:
    before = len(scan_project(workspace))
    run_dir = next((workspace / "runs").iterdir())
    (run_dir / ARTIFACTS_DIRNAME / "leftover").mkdir(parents=True)

    assert len(scan_project(workspace)) == before


# --------------------------------------------------------------------------- #
# Lineage
# --------------------------------------------------------------------------- #


def test_parents_resolve(workspace: Path) -> None:
    artifacts = scan_project(workspace)
    index = index_by_id(artifacts)
    labelled = index["2026-08-26_1100_condition_gmm_clustering__labelled"]

    resolved, unresolved = parents_of(labelled, index)

    assert [a.artifact_id for a in resolved] == [
        "2026-08-26_1030_ricp_register__registered"
    ]
    assert unresolved == []


def test_an_input_that_is_not_an_artifact_is_reported_not_dropped(
    workspace: Path,
) -> None:
    """A file picked from raw/ was never produced by a run."""
    index = index_by_id(scan_project(workspace))
    canonical = index["2026-08-26_0900_tlsphoto_ingest__canonical"]

    resolved, unresolved = parents_of(canonical, index)

    assert resolved == []
    assert unresolved == ["raw/site.e57"]


def test_ancestors_walk_the_whole_chain(workspace: Path) -> None:
    index = index_by_id(scan_project(workspace))
    labelled = index["2026-08-26_1100_condition_gmm_clustering__labelled"]

    chain = [a.artifact_id for a in ancestors_of(labelled, index)]

    assert chain == [
        "2026-08-26_1030_ricp_register__registered",
        "2026-08-26_0900_tlsphoto_ingest__canonical",
    ]


def test_ancestors_of_a_root_artifact(workspace: Path) -> None:
    index = index_by_id(scan_project(workspace))
    canonical = index["2026-08-26_0900_tlsphoto_ingest__canonical"]
    assert ancestors_of(canonical, index) == []


def test_ancestors_survive_a_cycle() -> None:
    a = Artifact(artifact_id="a", type="table", files=("f",), inputs=("b",))
    b = Artifact(artifact_id="b", type="table", files=("f",), inputs=("a",))
    index = index_by_id([a, b])

    assert [x.artifact_id for x in ancestors_of(a, index)] == ["b"]
