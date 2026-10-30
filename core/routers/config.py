from fastapi import APIRouter, Body
from .. import config as cfg_module
from ..config import save_config, logger

router = APIRouter(tags=["Config"])

@router.get("/config")
def get_runtime_config():
    return cfg_module.runtime_config

@router.post("/config")
def update_config(new_cfg: dict = Body(...)):
    try:
        old_nodes = {
            n.get("id"): n
            for n in cfg_module.runtime_config.get("NODES", [])
            if isinstance(n, dict) and n.get("id")
        }

        updated = dict(cfg_module.runtime_config)
        for k, v in new_cfg.items():
            updated[k] = v

        # DÜZELTME 5: teamleadModel senkronizasyonu.
        # Kullanıcı UI üzerinden model değiştirdiğinde eski teamleadModel takılı kalmamalı.
        for node in updated.get("NODES", []):
            nid = node.get("id")
            old_node = old_nodes.get(nid, {})
            new_model = node.get("model", "")
            old_model = old_node.get("model", "")
            old_tl = old_node.get("teamleadModel", "")

            if not node.get("teamleadModel"):
                node["teamleadModel"] = new_model
                logger.info(f"Auto-filled teamleadModel for node '{node.get('name', nid)}'")
            elif new_model and new_model != old_model and node.get("teamleadModel") == old_tl:
                # Model UI'dan değiştirildi fakat teamleadModel eski değerde kaldıysa eşitle
                node["teamleadModel"] = new_model
                logger.info(f"Synced teamleadModel='{new_model}' for node '{node.get('name', nid)}'")

        # Persist to data/config.json and refresh globals
        save_config(updated)

        redacted_log = {
            **updated,
            "NODES": [
                {**n, "apiKey": "***" if n.get("apiKey") else ""}
                for n in updated.get("NODES", [])
            ],
        }
        logger.info(f"Configuration updated: {redacted_log}")
        return {"status": "ok", "config": cfg_module.runtime_config}
    except Exception as e:
        logger.error(f"Failed to update config: {e}")
        return {"status": "error", "message": str(e)}
