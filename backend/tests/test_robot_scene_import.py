import hashlib,json
import pytest
from robot_data_contracts.asset import AssetDraft
from robot_data_studio.services.asset_service import AssetRegistry,AssetConflict,AssetIntegrityError
from robot_data_studio.services.robot_scene_importer import import_robot_scenes,SOURCE

def pack(tmp):
    src=tmp/"source";src.mkdir();(src/"scene.usda").write_text("#usda 1.0\n");b=(src/"scene.usda").read_bytes()
    art=dict(source_id=SOURCE,path="scene.usda",role="model",sha256=hashlib.sha256(b).hexdigest(),size_bytes=len(b))
    model=AssetDraft(asset_id="MDL-rcloth-test",kind="model",name="test",artifacts=[art],change_note="test").model_dump(mode="json")
    scene=AssetDraft(asset_id="SCN-rcloth-test",kind="scene",name="test scene",references=[dict(asset_id="MDL-rcloth-test",version=1,role="model")],change_note="test").model_dump(mode="json")
    data=dict(schema_version=1,assets=[scene,model]);(src/"registry_manifest.json").write_text(json.dumps(data))
    cfg=tmp/"sources.json";cfg.write_text(json.dumps(dict(schema_version=1,sources={SOURCE:dict(root=str(src))})))
    return AssetRegistry(tmp/"registry",cfg),src,data

def test_dry_run_idempotency(tmp_path):
    r,s,d=pack(tmp_path)
    assert import_robot_scenes(r,True)["assets"]==2
    assert not r.root.exists()
    assert import_robot_scenes(r)["created"]==2
    old=(r.root/"MDL-rcloth-test/v000001.json").read_bytes()
    assert import_robot_scenes(r)["unchanged"]==2
    assert (r.root/"MDL-rcloth-test/v000001.json").read_bytes()==old
    assert r.integrity(r.get("SCN-rcloth-test"))["status"]=="current"

def test_all_preflight_before_publish(tmp_path):
    r,s,d=pack(tmp_path);(s/"scene.usda").write_text("tampered")
    with pytest.raises(AssetIntegrityError):import_robot_scenes(r)
    assert not r.root.exists()

def test_user_revision_preserved(tmp_path):
    r,s,d=pack(tmp_path);import_robot_scenes(r)
    body=r.get("MDL-rcloth-test").model_dump(include=set(AssetDraft.model_fields));body["name"]="user revision"
    r.publish(AssetDraft.model_validate(body),expected_version=1)
    assert import_robot_scenes(r)["unchanged"]==2
    assert r.get("MDL-rcloth-test").name=="user revision"

def test_conflict_rejected(tmp_path):
    r,s,d=pack(tmp_path);import_robot_scenes(r);d["assets"][1]["name"]="changed"
    (s/"registry_manifest.json").write_text(json.dumps(d))
    with pytest.raises(AssetConflict):import_robot_scenes(r)
    assert len(r.versions("MDL-rcloth-test"))==1

def test_cycles_rejected(tmp_path):
    r,s,d=pack(tmp_path);d["assets"][1]["references"]=[dict(asset_id="SCN-rcloth-test",version=1,role="cycle")]
    (s/"registry_manifest.json").write_text(json.dumps(d))
    with pytest.raises(ValueError,match="cyclic"):import_robot_scenes(r)
    assert not r.root.exists()

def test_dependency_version_checked(tmp_path):
    r,s,d=pack(tmp_path);d["assets"][0]["references"][0]["version"]=2
    (s/"registry_manifest.json").write_text(json.dumps(d))
    with pytest.raises(ValueError,match="v1"):import_robot_scenes(r)
