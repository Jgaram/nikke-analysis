from nikke_analysis.util.snapshot import SnapshotWriter, list_runs


def test_runs_in_the_same_second_never_share_a_directory(tmp_path):
    first = SnapshotWriter("source", run_id="20260924T000000Z", root=tmp_path)
    first.write("a.json", b"{}", url="u")
    first.seal()

    # An idle run started in the same second discards only its own directory.
    idle = SnapshotWriter("source", run_id="20260924T000000Z", root=tmp_path)
    assert idle.dir != first.dir
    idle.discard()

    second = SnapshotWriter("source", run_id="20260924T000000Z", root=tmp_path)
    second.write("b.json", b"{}", url="u")
    second.seal()
    assert [run.run_id for run in list_runs("source", root=tmp_path)] == ["20260924T000000Z", "20260924T000000Z-002"]
