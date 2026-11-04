from fastapi import APIRouter, Request


def create_rules_router(store, parser=None):
    router = APIRouter(prefix="/api")

    @router.get("/rules")
    async def get_rules():
        return store.read_rules()

    @router.post("/rules/apply")
    async def apply_rules(request: Request):
        body = await request.json()
        current = store.read_rules()
        saved = store.write_rules({
            "rules": body.get("rules", []),
            "routes": body.get("routes", current.get("routes", {})),
        }, expected_revision=body.get("revision"))
        store.audit("rule.apply", "rules", "applied rule set", {"revision": saved["revision"]})
        return saved

    @router.post("/rules/rollback")
    async def rollback_rules(request: Request):
        body = await request.json()
        revision = body.get("revision", 0)
        saved = store.rollback_rules(revision)
        store.audit("rule.rollback", "rules", "rolled back rule set", {"revision": revision})
        return saved

    @router.post("/commands/parse")
    async def parse_command(request: Request):
        body = await request.json()
        if parser is None:
            return {"operations": [], "status": "parser_unavailable"}
        operations = parser.parse(body.get("text", ""))
        return {"operations": [item.model_dump() for item in operations], "status": "draft"}

    return router
