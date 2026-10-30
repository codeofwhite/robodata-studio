import argparse
import json

from .services.asset_service import AssetRegistry
from .services.robot_scene_importer import import_robot_scenes
from .services.clothforge_importer import import_clothforge
from .services.asset_importers import (
    import_bimanual_tabletop,
    import_cloth,
    import_visual_workstation,
)
from .services.validation_overview import link_validation_videos


def main():
    parser = argparse.ArgumentParser(description="Versioned Studio asset registry")
    sub = parser.add_subparsers(dest="command", required=True)
    importer = sub.add_parser("import")
    importer.add_argument(
        "--source",
        choices=[
            "cloth-batch-v1",
            "visual-workstation-v1",
            "visual-bimanual-tabletop-v1",
            "robot-cloth-scenes-v1",
            "clothforge-repair-v2",
        ],
        required=True,
    )
    importer.add_argument("--dry-run", action="store_true")
    videos = sub.add_parser("link-validation-videos")
    videos.add_argument("--dry-run", action="store_true")
    sub.add_parser("verify")
    args = parser.parse_args()
    registry = AssetRegistry()
    if args.command == "import":
        if args.source == "clothforge-repair-v2":
            report = import_clothforge(registry, args.dry_run)
        elif args.source == "robot-cloth-scenes-v1":
            report = import_robot_scenes(registry, args.dry_run)
        elif args.source == "cloth-batch-v1":
            report = import_cloth(registry, args.dry_run)
        elif args.source == "visual-workstation-v1":
            report = import_visual_workstation(registry, args.dry_run)
        else:
            report = import_bimanual_tabletop(registry, args.dry_run)
    elif args.command == "link-validation-videos":
        report = link_validation_videos(registry, args.dry_run)
    else:
        records = registry.all()
        lookup = {(r.asset_id, r.version): r for r in records}
        bad = []
        for record in records:
            result = registry.integrity(record, lookup)
            if result["status"] != "current":
                bad.append({"asset_id": record.asset_id, "version": record.version, **result})
        report = {"revisions": len(records), "errors": bad, "passed": bool(records) and not bad}
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if args.command == "verify" and not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
