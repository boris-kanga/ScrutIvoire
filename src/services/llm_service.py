import json
import os
import re

from thefuzz import fuzz, process

from src.core.config import LLM_DB_URI, LLM_SLIDING_WINDOW_DEEP, WORK_DIR
from src.domain.llm import LLMMessage
from src.infrastructure.database.pgdb import PgDB
from src.repository.llm_repo import LLMRepo
from src.utils.tools import cache


SQL_INJECTED_TAG = "[SYSTEM_CONTEXT : SQL_SCHEMA]"


class LLMService:
    def __init__(
            self,
            entity_resolution,
            llm_repo: LLMRepo=None,
            llm_db: PgDB=None,
            sliding_window=LLM_SLIDING_WINDOW_DEEP,
            max_successive_error=3
        ):
        if llm_repo is None:
            llm_repo = LLMRepo()

        if llm_db is None:
            llm_db = PgDB(dsn=LLM_DB_URI, as_client=True)

        self.llm_repo = llm_repo
        self.llm_db = llm_db
        self.sliding_window = sliding_window
        self.entity_resolution = entity_resolution
        self.max_successive_error = max_successive_error


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

    async def dispatch_tool(self, func_name, args, election_id):
        print("le llm demande d'appeler:", func_name, args, election_id)
        if func_name == "fuzzy_wuzzy":
            if not args.get("entity") or not args.get("category"):
                return "REQUIRED `entity` and `category`"
            res = await self.entity_resolution(
                args.get("entity"),
                args.get("category"),
                election_id
            )
            if not res:
                return "Not Found"
            return res
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
                res = await self.llm_db.run_query(args.get("query"))
                return {"ok": True, "result": res}
            except Exception as e:
                return {
                    "ok": False, "error": str(e),
                    "query": query
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

    async def answer(self, question, election_id, session_id, callback):
        _context = await self.llm_db.run_query("""
            SELECT 
                * 
            FROM chat_session 
            WHERE 
                session_id=$1 AND 
                status = 'DONE' 
            ORDER BY answer_time DESC
            LIMIT $2
        """, params=(session_id, self.sliding_window))
        print(_context)
        history = []
        has_sql_injected = False

        for c in _context[::-1]:
            try:
                messages = json.loads(c["answer_meta"])["messages"]
                for msg in messages:
                    content = msg.get("content") or ""
                    if SQL_INJECTED_TAG in content:
                        has_sql_injected = True
                    history.append(
                        LLMMessage(
                            role=msg["role"],
                            content=content,
                            tool_calls=msg.get("tool_calls"),
                            tool_call_id=msg.get("tool_call_id"),
                        )
                    )
            except json.JSONDecodeError:
                pass

        base = self.llm_repo.get_prompt(
            task_type="chat",
            system_arg=dict(election_id=election_id)
        ) + history

        message_accumulator = [
            LLMMessage(
                role="user",
                content=question,
            )
        ]



        result = await self.llm_repo.router.run(
            task_type="chat",
            messages=base + message_accumulator,
            payload={},
            tools=self.get_tools(),
            tool_choice="auto",
            response_format="json"
        )
        print("\n\n")
        print(result)
        if callback is not None:
            await callback(result, message_accumulator)

        successive_error = 0
        while result["tool_calls"]:
            # Exécuter les outils demandés
            tool_results = []
            for tc in result["tool_calls"]:
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
                output = await self.dispatch_tool(
                    tc["name"], tc["arguments"], election_id
                )
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
                            result = {
                                "result": {"display": "TEXT", "text": "Une erreur s'est produite...", "error": True},
                                "success": False,
                                "tool_calls": []
                            }
                            if callback is not None:
                                await callback(result, message_accumulator)
                            return result["result"]

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
                    content=str(output),
                    tool_call_id=tid,  # lie le résultat à l'appel
                ))

            result = await self.llm_repo.router.run(
                task_type="chat",
                messages=base + message_accumulator,
                payload={},
                tools=self.get_tools(),
                tool_choice="auto",
                response_format="json"
            )
            print("\n\n")
            print(result)
            if callback is not None:
                await callback(result, message_accumulator)
        return result["result"]


if __name__ == '__main__':
    import asyncio

    asyncio.run(LLMService().answer("", "", None))


