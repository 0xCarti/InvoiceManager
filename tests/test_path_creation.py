def test_creates_paths(app, tmp_path):
    assert (tmp_path / 'inventory.db').exists()
    assert (tmp_path / 'uploads').is_dir()
    assert (tmp_path / 'backups').is_dir()
    assert (tmp_path / 'import_files').is_dir()
