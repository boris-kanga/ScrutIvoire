import json
import os
import re

from src.core.config import LLM_DB_URI, LLM_SLIDING_WINDOW_DEEP, WORK_DIR
from src.domain.llm import LLMMessage
from src.infrastructure.database.pgdb import PgDB
from src.repository.entity_resolution import EntityResolution, EntityResolver, \
    BestEntity
from src.repository.llm_repo import LLMRepo
from src.utils.tools import cache


SQL_INJECTED_TAG = "[SYSTEM_CONTEXT : SQL_SCHEMA]"


class LLMService:
    def __init__(
            self,
            entity_resolution: EntityResolution=None,
            llm_repo: LLMRepo=None,
            llm_db: PgDB=None,
            sliding_window=LLM_SLIDING_WINDOW_DEEP,
            max_successive_error=3,
            consecutive_empty_sql_res_th=3
        ):
        if llm_repo is None:
            llm_repo = LLMRepo()

        if llm_db is None:
            llm_db = PgDB(dsn=LLM_DB_URI, as_client=True)
        if entity_resolution is None:
            entity_resolution = EntityResolution(llm_db)

        self.llm_repo = llm_repo
        self.llm_db = llm_db
        self.sliding_window = sliding_window
        self.entity_resolution: EntityResolution = entity_resolution
        self.max_successive_error = max_successive_error
        self.consecutive_empty_sql_res_th = consecutive_empty_sql_res_th


    async def detect_columns(self, columns, name=None):
        messages = self.llm_repo.get_prompt(
            task_type="column_detector",
            user_arg=dict(title=name, columns=columns),
            system_arg=dict(title=name)
        )
        return await self.llm_repo.run(
            "column_detector",
            messages, {}, timeout=60
        )

    @cache()
    def get_tools(self):
        with open(os.path.join(WORK_DIR, "data", "prompts", "tools", "chat.json")) as f:
            return json.loads(f.read())

    async def dispatch_tool(self, func_name, args, election_id, source_context):
        print("le llm demande d'appeler:", func_name, args, election_id)
        if func_name == "fuzzy_wuzzy":
            if not args.get("entity") or not args.get("category"):
                return "REQUIRED `entity` and `category`"
            category = str(args.get("category")).upper()
            entity_res: EntityResolver = await self.entity_resolution.resolve(
                args.get("entity"),
                category,
                election_id
            )
            return entity_res
        if func_name == "execute_sql_query":
            query = (args.get("query") or "").rstrip("; ").strip()

            if not query:
                return {
                    "ok": False, "error": "bad query got: Required valid SQL",
                    "query": query
                }

            has_aggregation = bool(
                re.search(r'\b(SUM|COUNT|AVG|MAX|MIN)\s*\(', query,
                          re.IGNORECASE))
            has_group_by = bool(
                re.search(r'\bGROUP\s+BY\b', query, re.IGNORECASE))

            needs_limit = not (has_aggregation and not has_group_by)

            if needs_limit and "limit" not in query.lower():
                query += " LIMIT 100"
            try:
                res = await self.llm_db.run_query(query)
                return {"ok": True, "result": res, "query": args.get("query")}
            except Exception as e:
                print("\tLa requete a echoue:", e)
                return {
                    "ok": False, "error": str(e),
                    "query": args.get("query")
                }

        if func_name == "get_table_evidence":
            circonscription_id = args.get("circonscription_id")
            candidate_id = args.get("candidate_id")

            if circonscription_id:
                return await self.llm_db.run_query(
                    """
                    SELECT * FROM circonscriptions
                    WHERE id=$1
                    """, params=(circonscription_id,)
                )

            return await self.llm_db.run_query(
                """
                SELECT * FROM candidates
                WHERE id=$1
                """, params=(candidate_id, )
            )
        return None

    async def answer(self, question, options, election_id, session_id, callback):

        source_context = {
            "circ_ids": set(),
            "cand_ids": set(),
        }

        _context = await self.llm_db.run_query("""
            SELECT 
                * 
            FROM chat_session 
            WHERE 
                session_id=$1 AND 
                status = 'DONE' 
            ORDER BY answer_time DESC
            LIMIT $2
        """, params=(session_id, self.sliding_window + int(bool(options))))
        history = []
        has_sql_injected = False
        options = options or []
        # [{tool_id, origin, category, id, canonic_name}, ...]
        for res in options:
            if res["category"] in ("COMMUNE", "SOUS_PREFECTURE", "ZONE"):
                source_context["circ_ids"].add(res["id"])
            elif res["category"] == "CANDIDATE":
                source_context["cand_ids"].add(res["id"])

        options = {
            opt["tool_id"]: EntityResolver(
                origin=opt["origin"],
                category=opt["category"],
                found=True,
                best=BestEntity(
                    id=opt["id"],
                    canonic_name=opt["canonic_name"],
                    score=100
                )

            )
            for opt in options
        }

        content_length = len(_context)
        for i, c in enumerate(_context[::-1]):
            try:
                messages = json.loads(c["answer_meta"])["messages"]
                for msg in messages:

                    if i == content_length - 1:
                        content = options.get(msg.get("tool_call_id"))
                        if not content:
                            content = msg.get("content") or ""
                            if SQL_INJECTED_TAG in content:
                                has_sql_injected = True
                    else:
                        content = msg.get("content") or ""
                        if SQL_INJECTED_TAG in content:
                            has_sql_injected = True

                    history.append(
                        LLMMessage(
                            role=msg["role"],
                            content=str(content),
                            tool_calls=msg.get("tool_calls"),
                            tool_call_id=msg.get("tool_call_id"),
                        )
                    )
            except json.JSONDecodeError:
                pass

        for h in history:
            print("\n-->",h.role, "\n\t", h.content[:200])

        base = self.llm_repo.get_prompt(
            task_type="chat",
            system_arg=dict(election_id=election_id)
        ) + history

        message_accumulator = []

        if not options:
            message_accumulator = [
                LLMMessage(
                    role="user",
                    content=question,
                )
            ]
        elif not has_sql_injected:
            history[-1].content = self.llm_repo.get_prompt(
                j2_file="chat.sql_schema_injection",
                output=history[-1].content,
                tag=SQL_INJECTED_TAG,
            )[0].content
            has_sql_injected = True

        total_prompt_tokens, total_completion_tokens = 0, 0
        result = await self.llm_repo.router.run(
            task_type="chat",
            messages=base + message_accumulator,
            payload={},
            tools=self.get_tools(),
            tool_choice="auto",
            response_format="json"
        )
        if result["success"]:
            total_prompt_tokens += result["prompt_tokens"]
            total_completion_tokens += result["completion_tokens"]

        print("\n\n")
        print(result)
        if callback is not None:
            await callback(
                    result,
                    message_accumulator,
                    total_prompt_tokens=total_prompt_tokens,
                    total_completion_tokens=total_completion_tokens
                )

        successive_error = 0
        last_sql = None
        consecutive_empty_sql_res = 0
        any_options = []

        error_msg = {
            "result": {
                "display": "TEXT",
                "text": "Une erreur s'est produite...",
                "error": True
            },
            "success": False,
            "tool_calls": []
        }
        while result["tool_calls"]:
            # Exécuter les outils demandés
            tool_results = []
            for tc in result["tool_calls"]:
                # before call tools
                if tc["name"] == "execute_sql_query" and not has_sql_injected:
                    output = self.llm_repo.get_prompt(
                        j2_file="chat.sql_schema_injection",
                        output="Erreur",
                        tag=SQL_INJECTED_TAG
                    )[0].content
                    has_sql_injected = True
                    tool_results.append(
                        (tc["id"], tc["name"], tc["arguments"], output))
                    continue
                if tc["name"] == "execute_sql_query":
                    if (tc["name"], tc["arguments"]) == last_sql:
                        if callback is not None:
                            await callback(
                                error_msg,
                                message_accumulator,
                                total_prompt_tokens=total_prompt_tokens,
                                total_completion_tokens=total_completion_tokens
                            )
                        return error_msg["result"]
                    last_sql = (tc["name"], tc["arguments"])
                # call tools
                output = await self.dispatch_tool(
                    tc["name"], tc["arguments"], election_id, source_context
                )

                # after tools
                if isinstance(output, EntityResolver):
                    if output.ambiguous:
                        any_options.append(
                            {
                                "tool_id": tc["id"],
                                "category": output.category,
                                "origin": output.origin,
                                "suggestions": [
                                    e.to_dict()
                                    for e in output.suggestions
                                ]
                            }
                        )
                    elif output:
                        if output.category in ("COMMUNE", "SOUS_PREFECTURE", "ZONE"):
                            source_context["circ_ids"].add(output.best.id)
                        elif output.category == "CANDIDATE":
                            source_context["cand_ids"].add(output.best.id)

                if tc["name"] == "fuzzy_wuzzy" and not has_sql_injected:
                    output = self.llm_repo.get_prompt(
                        j2_file="chat.sql_schema_injection",
                        output=output,
                        tag=SQL_INJECTED_TAG
                    )[0].content
                    has_sql_injected = True

                if tc["name"] == "execute_sql_query":
                    if not output["ok"]:
                        successive_error += 1

                        if successive_error > self.max_successive_error:
                            if callback is not None:
                                await callback(
                                    error_msg,
                                    message_accumulator,
                                    total_prompt_tokens=total_prompt_tokens,
                                    total_completion_tokens=total_completion_tokens
                                )
                            return error_msg["result"]

                    if not output.get("result"):
                        consecutive_empty_sql_res += 1
                        if consecutive_empty_sql_res > self.consecutive_empty_sql_res_th:
                            if callback is not None:
                                await callback(
                                    error_msg,
                                    message_accumulator,
                                    total_prompt_tokens=total_prompt_tokens,
                                    total_completion_tokens=total_completion_tokens
                                )
                            return error_msg["result"]

                tool_results.append((tc["id"], tc["name"], tc["arguments"], output))

            # Ajouter le tour assistant + résultats dans l'historique
            print("le retour des outils:", tool_results)
            message_accumulator.append(LLMMessage(
                role="assistant",
                content="",
                tool_calls=[
                    {"id": tid, "type": "function",
                     "function": {"name": tname, "arguments": json.dumps(args)}}
                    for tid, tname, args, _ in tool_results
                ],
            ))
            for tid, tname, _, output in tool_results:
                message_accumulator.append(LLMMessage(
                    role="tool",
                    content=json.dumps(output, default=str),
                    tool_call_id=tid,  # lie le résultat à l'appel
                ))

            if any_options:
                result = {
                    "result": {
                        "display": "OPTIONS",
                        "text": "Merci de confirmer voix choix",
                        "options": any_options
                    },
                    "success": True,
                    "tool_calls": []
                }
                if callback is not None:
                    await callback(
                        result,
                        message_accumulator,
                        total_prompt_tokens=total_prompt_tokens,
                        total_completion_tokens=total_completion_tokens
                    )
                return result["result"]

            result = await self.llm_repo.router.run(
                task_type="chat",
                messages=base + message_accumulator,
                payload={},
                tools=self.get_tools(),
                tool_choice="auto",
                response_format="json"
            )
            if result["success"]:
                total_prompt_tokens += result["prompt_tokens"]
                total_completion_tokens += result["completion_tokens"]

            print("\n\n")
            print(result)
            if callback is not None:
                await callback(
                    result,
                    message_accumulator,
                    total_prompt_tokens=total_prompt_tokens,
                    total_completion_tokens=total_completion_tokens
                )

        source = await self.compile_source(
            source_context["circ_ids"],
            source_context["cand_ids"],
        )
        # on calcul la source
        if result.get("result"):
            result["result"]["source"] = source

        return result["result"]

    async def compile_source(
            self,
            circ_ids: set[int],
            cand_ids: set[int],
    ):

        total = len(circ_ids) + len(cand_ids)
        if total == 0:
            return None

        if total <= 3:
            # --- Cas crops ---
            items = []

            if circ_ids:
                rows = await self.llm_db.run_query("""
                    SELECT id, crop_url, original_raw_name as name
                    FROM circonscriptions
                    WHERE id = ANY($1) AND crop_url IS NOT NULL
                """, params=(list(circ_ids),))
                items += [{"type": "circ", "id": r["id"], "url": r["crop_url"]}
                          for r in rows]

            if cand_ids:
                rows = await self.llm_db.run_query("""
                    SELECT id, crop_url, original_raw_name as name
                    FROM candidates
                    WHERE id = ANY($1) AND crop_url IS NOT NULL
                """, params=(list(cand_ids),))
                items += [{"type": "cand", "id": r["id"], "url": r["crop_url"], "name": r["name"]}
                          for r in rows]

            if not items:
                return None

            return {"type": "crops", "items": items}

        elif total <= 10:
            # --- Cas pages précises ---
            # Extraire les numéros de pages depuis bbox_json {page_index: [x0,top,x1,bottom]}
            pages = set()
            document_url = None

            if circ_ids:
                rows = await self.llm_db.run_query("""
                    SELECT c.bbox_json, sd.storage_url
                    FROM circonscriptions c
                    JOIN source_documents sd ON c.source_id = sd.id
                    WHERE c.id = ANY($1) AND c.bbox_json IS NOT NULL
                """, params=(list(circ_ids),))
                for row in rows:
                    document_url = document_url or row["storage_url"]
                    bbox = json.loads(row["bbox_json"])
                    pages.update(int(k) for k in bbox.keys())

            if cand_ids:
                rows = await self.llm_db.run_query("""
                    SELECT ca.bbox_json, sd.storage_url
                    FROM candidates ca
                    JOIN source_documents sd ON ca.source_id = sd.id
                    WHERE ca.id = ANY($1) AND ca.bbox_json IS NOT NULL
                """, params=(list(cand_ids),))
                for row in rows:
                    document_url = document_url or row["storage_url"]
                    bbox = json.loads(row["bbox_json"])
                    pages.update(int(k) for k in bbox.keys())

            if not document_url:
                return None

            return {
                "type": "pages",
                "url": document_url,
                "pages": sorted(pages),
            }

        else:
            # --- Cas document complet ---
            row = None
            if circ_ids:
                rows = await self.llm_db.run_query("""
                    SELECT sd.storage_url
                    FROM circonscriptions c
                    JOIN source_documents sd ON c.source_id = sd.id
                    WHERE c.id = ANY($1)
                    LIMIT 1
                """, params=(list(circ_ids),))
                row = rows[0] if rows else None

            if not row and cand_ids:
                rows = await self.llm_db.run_query("""
                    SELECT sd.storage_url
                    FROM candidates ca
                    JOIN source_documents sd ON ca.source_id = sd.id
                    WHERE ca.id = ANY($1)
                    LIMIT 1
                """, params=(list(cand_ids),))
                row = rows[0] if rows else None

            if not row:
                return None

            return {"type": "document", "url": row["storage_url"]}


if __name__ == '__main__':
    import asyncio

    asyncio.run(LLMService().answer("", "", None))


