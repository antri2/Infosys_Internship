"""Coordinating layer over the M3 agents.

Routes use this class for context loading, caching, generation, and saving.
The current project intentionally keeps orchestration lightweight and does
not introduce a new agent framework.
"""
from copy import deepcopy
import logging
from typing import Any

from services.context_builder import build_agent_context, get_candidate_context, get_job_context
from services import (
    skill_gap_service,
    resume_agent,
    cover_letter_agent,
    interview_agent,
    career_assistant_agent,
)
from services.job_matcher import compute_match


logger = logging.getLogger(__name__)


class AgentOrchestrator:
    def __init__(self, db, user_id: int):
        self.db = db
        self.user_id = user_id

    def _cached_skill_gap(self, candidate: dict, job: dict):
        report = skill_gap_service.load_cached_report(
            self.db, self.user_id, int(job["job_id"])
        )
        if not report:
            return None
        return skill_gap_service.add_verified_skill_sections(report, candidate, job)

    # ---------------- Skill Gap (M3.1) ----------------
    def run_skill_gap(self, job_id: int, force_refresh: bool = False) -> dict:
        candidate, job = build_agent_context(self.db, self.user_id, job_id)
        if job is None:
            raise ValueError(f"No job found with id {job_id}.")

        if not force_refresh:
            cached = self._cached_skill_gap(candidate, job)
            if cached:
                cached["from_cache"] = True
                return cached

        report = skill_gap_service.generate_skill_gap_report(candidate, job)
        skill_gap_service.save_skill_gap_report(self.db, self.user_id, job_id, report)
        report["from_cache"] = False
        return report

    def get_cached_skill_gap(self, job_id: int) -> dict | None:
        candidate, job = build_agent_context(self.db, self.user_id, job_id)
        if job is None:
            raise ValueError(f"No job found with id {job_id}.")
        return self._cached_skill_gap(candidate, job)

    # ---------------- Resume Customization (M3.2a) ----------------
    @staticmethod
    def _resume_cache_matches(tailored: dict, custom_instructions: str) -> bool:
        if tailored is None:
            return False
        saved = str(tailored.get("custom_instructions") or "").strip()
        requested = str(custom_instructions or "").strip()
        return saved == requested

    def get_cached_resume_builder(
        self,
        job_id: int,
        template: str = "chronological",
        custom_instructions: str = "",
        require_matching_instructions: bool = True,
    ) -> dict | None:
        candidate, job = build_agent_context(self.db, self.user_id, job_id)
        if job is None:
            raise ValueError(f"No job found with id {job_id}.")
        custom_instructions = resume_agent.normalize_custom_instructions(custom_instructions)
        tailored = resume_agent.load_cached_resume(self.db, self.user_id, job_id)
        if tailored is None or (
            require_matching_instructions
            and not self._resume_cache_matches(tailored, custom_instructions)
        ):
            return None
        tailored["from_cache"] = True
        tailored["template"] = template
        if not tailored.get("user_approved") or not tailored.get("resume_text"):
            tailored["resume_text"] = resume_agent.render_resume_text(tailored, template)
        tailored["skill_gap"] = self._cached_skill_gap(candidate, job)
        return tailored

    def run_resume_builder(
        self,
        job_id: int,
        template: str = "chronological",
        force_refresh: bool = False,
        custom_instructions: str = "",
        target_role: str = "",
    ) -> dict:
        candidate, job = build_agent_context(self.db, self.user_id, job_id)
        if job is None:
            raise ValueError(f"No job found with id {job_id}.")
        custom_instructions = resume_agent.normalize_custom_instructions(custom_instructions)

        tailored = None if force_refresh else resume_agent.load_cached_resume(
            self.db, self.user_id, job_id
        )
        from_cache = tailored is not None and self._resume_cache_matches(
            tailored, custom_instructions
        )
        if not from_cache:
            agent_job = dict(job)
            if target_role:
                # Keep the internal cache key stable while presenting the
                # Resume Agent with role-level context rather than a selected
                # company posting.
                agent_job["title"] = target_role
                agent_job["company"] = ""
            tailored = resume_agent.generate_tailored_resume(
                candidate,
                agent_job,
                custom_instructions=custom_instructions,
                target_role=target_role or job.get("title", ""),
                template=template,
            )
            resume_agent.save_tailored_resume(
                self.db, self.user_id, job_id, tailored
            )

        tailored["from_cache"] = from_cache
        tailored["template"] = template
        tailored["target_role"] = target_role or tailored.get("target_role") or job.get("title", "")
        if not tailored.get("user_approved") or not tailored.get("resume_text"):
            tailored["resume_text"] = resume_agent.render_resume_text(tailored, template)
        tailored["skill_gap"] = self._cached_skill_gap(candidate, job)
        return tailored

    def save_resume_builder(
        self,
        job_id: int,
        resume_text: str,
        template: str = "chronological",
        custom_instructions: str = "",
        target_role: str = "",
    ) -> dict:
        """Persist the exact approved text and apply only explicit profile additions."""
        candidate, job = build_agent_context(self.db, self.user_id, job_id)
        if job is None:
            raise ValueError(f"No job found with id {job_id}.")
        if not isinstance(resume_text, str) or not resume_text.strip():
            raise ValueError("Resume content is required.")
        if len(resume_text) > 100000:
            raise ValueError("Resume content is too long.")

        custom_instructions = resume_agent.normalize_custom_instructions(custom_instructions)
        tailored = resume_agent.load_cached_resume(self.db, self.user_id, job_id)
        if tailored is None:
            raise ValueError("Generate a resume before saving.")

        approved = deepcopy(tailored)
        approved["name"] = candidate.get("name") or approved.get("name") or "Candidate"
        approved["resume_text"] = resume_text
        approved["template"] = template if template in resume_agent.TEMPLATES else "chronological"
        approved["target_role"] = target_role or approved.get("target_role") or job.get("title", "")
        approved["custom_instructions"] = custom_instructions
        approved["user_approved"] = True
        approved["from_cache"] = True
        # Use the updates captured during generation, not an ungenerated edit to
        # the instruction box, so saving cannot introduce a fact the draft omitted.
        approved.setdefault("user_updates", resume_agent.parse_user_updates(custom_instructions))
        resume_agent.save_tailored_resume(self.db, self.user_id, job_id, approved)
        profile_updates = resume_agent.apply_user_updates(
            self.db,
            self.user_id,
            approved.get("user_updates"),
            resume_text,
        )
        approved["profile_updates"] = profile_updates
        return approved

    # ---------------- Interview Preparation (M3.3) ----------------
    @staticmethod
    def _interview_job_id(value: Any) -> int | None:
        if value in (None, ""):
            return None
        if isinstance(value, bool) or (
            isinstance(value, float) and not value.is_integer()
        ):
            raise ValueError("A valid job_id is required.")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("A valid job_id is required.") from exc
        if parsed <= 0:
            raise ValueError("A valid job_id is required.")
        return parsed

    @staticmethod
    def _interview_text(value: Any, limit: int, label: str) -> str:
        if value in (None, ""):
            return ""
        if not isinstance(value, str):
            raise ValueError(f"{label} must be text.")
        text = value.strip()
        if len(text) > limit:
            raise ValueError(f"{label} must be {limit} characters or fewer.")
        return text

    def _interview_context(
        self,
        target_role: str = "",
        job_id: int | None = None,
        company: str = "",
        job_description: str = "",
    ) -> tuple[dict, dict | None, dict | None, int | None, str]:
        """Resolve the interview target without ever inventing a database job.

        A job_id is used only when the user explicitly arrived from an
        Opportunity or an Application. A bare role never resolves a posting.
        """
        normalized_job_id = self._interview_job_id(job_id)
        candidate = get_candidate_context(self.db, self.user_id)
        company = self._interview_text(company, 200, "Company name")
        job_description = self._interview_text(
            job_description, interview_agent.MAX_TEXT_LENGTH, "Job description"
        )

        if normalized_job_id is not None:
            job = get_job_context(self.db, normalized_job_id)
            if job is None:
                raise ValueError(f"Job {normalized_job_id} was not found.")
            if not target_role:
                target_role = str(job.get("title") or "")
            return candidate, job, self._cached_skill_gap(candidate, job), normalized_job_id, "job"

        # No explicit job.  A pasted JD wins; otherwise use advisory role
        # context.  Neither path touches the jobs table.
        if job_description:
            match_job = skill_gap_service.build_jd_context(
                target_role, company, job_description
            )
            return candidate, match_job, None, None, "jd"

        if target_role:
            match_job = skill_gap_service.build_role_context(target_role, company)
            return candidate, match_job, None, None, "role"

        raise ValueError("Target role is required.")

    def run_interview_preparation(
        self,
        target_role: str,
        job_id: int | None = None,
        category: str = "technical",
        difficulty: str = "medium",
        count: int = 5,
        focus_areas: str = "",
        company: str = "",
        job_description: str = "",
    ) -> dict:
        """Run the complete interview workflow and persist validated output."""
        focus_areas = self._interview_text(focus_areas, 200, "Focus areas")
        candidate, job, skill_gap, normalized_job_id, context_mode = (
            self._interview_context(
                target_role, job_id, company, job_description
            )
        )
        context_label = {
            "job": "the exact Opportunity job the user selected",
            "jd": "a job description the user pasted",
            "role": "general role-level preparation (no specific job)",
        }[context_mode]
        result = interview_agent.generate_interview_content(
            candidate,
            job,
            skill_gap,
            target_role,
            category,
            difficulty,
            count,
            focus_areas=focus_areas,
            context_label=context_label,
        )
        normalized_role, normalized_category, normalized_difficulty = (
            " ".join(str(target_role or "").strip().split()),
            interview_agent.canonical_category(category),
            interview_agent.canonical_difficulty(difficulty),
        )
        saved_questions = interview_agent.save_questions(
            self.db,
            self.user_id,
            normalized_job_id,
            normalized_role,
            result["questions"],
        )
        interview_agent.save_plan(self.db, self.user_id, normalized_job_id, result["plan"])
        # Align stored ids with the returned questions so the mock interview
        # can record an answer (or a skip) against the exact question row.
        question_ids: list[int | None] = [None] * len(result["questions"])
        for index, question_id in saved_questions:
            if 0 <= index < len(question_ids):
                question_ids[index] = question_id
        result.update({
            "target_role": normalized_role,
            "category": normalized_category,
            "difficulty": normalized_difficulty,
            "difficulty_label": interview_agent.difficulty_label(normalized_difficulty),
            "category_label": interview_agent.category_label(normalized_category),
            "focus_areas": focus_areas,
            "company": company,
            "context_mode": context_mode,
            "job_id": normalized_job_id,
            "question_ids": question_ids,
            "skill_gap": skill_gap,
        })
        return result

    def get_interview_tip(
        self,
        question: str,
        target_role: str,
        category: str = "",
        difficulty: str = "",
        company: str = "",
        job_description: str = "",
    ) -> dict:
        """Short hint for the current question; never the full answer."""
        return interview_agent.generate_question_tip(
            question,
            target_role,
            category,
            difficulty,
            context_label=company or ("pasted job description" if job_description else ""),
        )

    def evaluate_interview_answer(
        self,
        question: str,
        user_answer: str,
        target_role: str,
        category: str = "",
        difficulty: str = "",
        company: str = "",
        job_description: str = "",
    ) -> dict:
        """Evaluate one mock-interview answer against the same grounded context."""
        candidate, job, skill_gap, _, _ = self._interview_context(
            target_role, None, company, job_description
        )
        return interview_agent.evaluate_interview_answer(
            candidate,
            job,
            skill_gap,
            target_role,
            question,
            user_answer,
            category,
            difficulty,
        )

    def summarize_interview_session(
        self,
        target_role: str,
        results: list[dict],
    ) -> dict:
        """Practice-only summary of a completed mock interview."""
        return interview_agent.build_mock_summary(target_role, results)

    # ---------------- Mock Interview session persistence ----------------
    def start_mock_interview(self, job_id: int | None = None) -> dict:
        """Open a mock session backed by the existing mock_interview tables."""
        normalized = self._interview_job_id(job_id)
        if normalized is not None and get_job_context(self.db, normalized) is None:
            raise ValueError(f"Job {normalized} was not found.")
        return {"session_id": interview_agent.start_mock_session(
            self.db, self.user_id, normalized
        )}

    def record_mock_answer(
        self,
        session_id: int,
        question_id: int,
        student_answer: str = "",
        feedback: dict | None = None,
        score: Any = None,
    ) -> None:
        interview_agent.save_mock_answer(
            self.db,
            self.user_id,
            int(session_id),
            int(question_id),
            student_answer,
            feedback,
            score,
        )

    def finish_mock_interview(self, session_id: int) -> None:
        interview_agent.finish_mock_session(self.db, self.user_id, int(session_id))

    def list_mock_interview_history(self, limit: int = 20) -> list[dict]:
        return interview_agent.list_mock_sessions(self.db, self.user_id, limit=limit)

    def load_mock_interview_history(self, session_id: int) -> dict | None:
        return interview_agent.load_mock_session(self.db, self.user_id, int(session_id))

    # Short aliases keep the orchestration API consistent with the other M3
    # agents while the descriptive method remains the canonical entry point.
    run_interview = run_interview_preparation
    generate_interview_questions = run_interview_preparation

    def list_recent_interview_data(
        self, question_limit: int = 20, plan_limit: int = 10
    ) -> dict:
        """Return persisted interview data without invoking an LLM."""
        return {
            "questions": interview_agent.list_recent_questions(
                self.db, self.user_id, limit=question_limit
            ),
            "plans": interview_agent.list_recent_plans(
                self.db, self.user_id, limit=plan_limit
            ),
        }

    # Compatibility-friendly name for callers that ask for saved preparation.
    get_interview_history = list_recent_interview_data

    # ---------------- Cover Letter (M3.2b) ----------------
    @staticmethod
    def _cover_letter_job_id(job_id: Any) -> int:
        if isinstance(job_id, bool) or (
            isinstance(job_id, float) and not job_id.is_integer()
        ):
            raise ValueError("A valid job_id is required.")
        try:
            normalized = int(job_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("A valid job_id is required.") from exc
        if normalized <= 0:
            raise ValueError("A valid job_id is required.")
        return normalized

    @staticmethod
    def _cover_letter_id(letter_id: Any) -> int:
        if isinstance(letter_id, bool) or (
            isinstance(letter_id, float) and not letter_id.is_integer()
        ):
            raise ValueError("A valid letter_id is required.")
        try:
            normalized = int(letter_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("A valid letter_id is required.") from exc
        if normalized <= 0:
            raise ValueError("A valid letter_id is required.")
        return normalized

    @staticmethod
    def _cover_letter_job_payload(job: dict | None) -> dict | None:
        if not job:
            return None
        return {
            "job_id": int(job["job_id"]),
            "title": job.get("title"),
            "company": job.get("company"),
            "location": job.get("location"),
        }

    def _cover_letter_context(
        self, job_id: int | None
    ) -> tuple[dict, dict, dict | None, dict | None]:
        candidate, job = build_agent_context(self.db, self.user_id, job_id)
        if job_id is not None and job is None:
            raise ValueError(f"Job {job_id} was not found.")
        if job is None:
            job = {}
        skill_gap = self._cached_skill_gap(candidate, job) if job else None
        tailored_resume = (
            resume_agent.load_cached_resume(self.db, self.user_id, job_id)
            if job_id is not None
            else None
        )
        return candidate, job, skill_gap, tailored_resume

    def generate_cover_letter(
        self, job_id: int | None, extra_context: str = ""
    ) -> dict:
        """Generate a validated, unsaved letter with optional job context."""
        normalized_job_id = (
            None if job_id in (None, "")
            else self._cover_letter_job_id(job_id)
        )
        candidate, job, skill_gap, tailored_resume = self._cover_letter_context(
            normalized_job_id
        )
        result = cover_letter_agent.generate_cover_letter(
            candidate,
            job,
            extra_context=extra_context,
            skill_gap=skill_gap,
            tailored_resume=tailored_resume,
        )
        result.update({
            "letter_id": None,
            "id": None,
            "job_id": normalized_job_id,
            "job": self._cover_letter_job_payload(job),
            "skill_gap": skill_gap,
            "tailored_resume_available": tailored_resume is not None,
        })
        return result

    def regenerate_cover_letter(
        self,
        letter_id: int,
        job_id: int | None = None,
        extra_context: str = "",
    ) -> dict:
        """Explicitly generate a fresh version without overwriting the saved row."""
        normalized_letter_id = self._cover_letter_id(letter_id)
        saved = cover_letter_agent.load_cover_letter(
            self.db, self.user_id, normalized_letter_id
        )
        if saved is None:
            raise cover_letter_agent.CoverLetterNotFound(
                "Cover letter was not found for this user."
            )
        saved_job_id = saved.get("job_id")
        if job_id not in (None, ""):
            requested_job_id = self._cover_letter_job_id(job_id)
            if saved_job_id is None or int(saved_job_id) != requested_job_id:
                raise ValueError("The selected job does not match the saved letter.")
            normalized_job_id = requested_job_id
        else:
            normalized_job_id = (
                None
                if saved_job_id in (None, "")
                else self._cover_letter_job_id(saved_job_id)
            )
        result = self.generate_cover_letter(normalized_job_id, extra_context)
        result["regenerated_from_letter_id"] = normalized_letter_id
        return result

    def save_cover_letter(
        self,
        content: str,
        job_id: int | None,
        letter_id: int | None = None,
    ) -> dict:
        """Persist exact edited text; this method never invokes the LLM."""
        normalized_letter_id = (
            self._cover_letter_id(letter_id) if letter_id not in (None, "") else None
        )
        saved = None
        if normalized_letter_id is not None:
            saved = cover_letter_agent.load_cover_letter(
                self.db, self.user_id, normalized_letter_id
            )
            if saved is None:
                raise cover_letter_agent.CoverLetterNotFound(
                    "Cover letter was not found for this user."
                )
            if job_id in (None, ""):
                job_id = saved.get("job_id")
        normalized_job_id = (
            None if job_id in (None, "")
            else self._cover_letter_job_id(job_id)
        )
        if saved is not None and saved.get("job_id") is not None:
            if (
                normalized_job_id is None
                or int(saved["job_id"]) != normalized_job_id
            ):
                raise ValueError("The selected job does not match the saved letter.")
        job = (
            get_job_context(self.db, normalized_job_id)
            if normalized_job_id is not None
            else None
        )
        if normalized_job_id is not None and job is None:
            raise ValueError(f"Job {normalized_job_id} was not found.")
        saved_id = cover_letter_agent.save_cover_letter(
            self.db,
            self.user_id,
            normalized_job_id,
            content,
            letter_id=normalized_letter_id,
        )
        row = cover_letter_agent.load_cover_letter(self.db, self.user_id, saved_id)
        if row is None:
            raise cover_letter_agent.CoverLetterNotFound(
                "Cover letter was not found for this user."
            )
        return {
            "id": saved_id,
            "letter_id": saved_id,
            "content": content,
            "job_id": normalized_job_id,
            "job": self._cover_letter_job_payload(job),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "saved": True,
        }

    def load_cover_letter(self, letter_id: int) -> dict:
        normalized_letter_id = self._cover_letter_id(letter_id)
        row = cover_letter_agent.load_cover_letter(
            self.db, self.user_id, normalized_letter_id
        )
        if row is None:
            raise cover_letter_agent.CoverLetterNotFound(
                "Cover letter was not found for this user."
            )
        return row

    def list_cover_letters(self) -> list[dict]:
        return cover_letter_agent.list_cover_letters(self.db, self.user_id)

    def run_cover_letter(
        self, job_id: int | None, extra_context: str = "", save: bool = True
    ) -> dict:
        """Backward-compatible wrapper; the UI uses generate then exact save."""
        result = self.generate_cover_letter(job_id, extra_context)
        if save:
            saved = self.save_cover_letter(
                result["cover_letter"], result["job_id"], result.get("letter_id")
            )
            result.update({
                "id": saved["id"],
                "letter_id": saved["id"],
                "content": saved["content"],
                "saved": True,
            })
        return result

    # ---------------- Career Assistant ----------------
    @staticmethod
    def _assistant_positive_id(value: Any, label: str) -> int:
        if isinstance(value, bool) or (
            isinstance(value, float) and not value.is_integer()
        ):
            raise ValueError(f"A valid {label} is required.")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"A valid {label} is required.") from exc
        if parsed <= 0:
            raise ValueError(f"A valid {label} is required.")
        return parsed

    def _assistant_context(
        self,
        message: str,
        job_id: int | None = None,
        target_role: str = "",
        pasted_jd: str = "",
        history: list[dict] | None = None,
    ) -> dict:
        candidate = get_candidate_context(self.db, self.user_id)
        job = None
        normalized_job_id = None
        if job_id not in (None, ""):
            normalized_job_id = self._assistant_positive_id(job_id, "job_id")
            job = get_job_context(self.db, normalized_job_id)
            if job is None:
                raise ValueError(f"Job {normalized_job_id} was not found.")

        pasted_jd = str(pasted_jd or "").strip()
        if len(pasted_jd) > 12000:
            raise ValueError("Pasted job description is too long.")
        # A role explicitly named in the current turn supersedes a role retained
        # from an earlier turn; ordinary follow-ups keep the existing context.
        message_role = career_assistant_agent.extract_target_role(message, "")
        target_role = message_role or career_assistant_agent.extract_target_role("", target_role)
        if job and not target_role:
            target_role = str(job.get("title") or "")

        role_hints = career_assistant_agent.role_skill_hints(target_role)
        match = None
        skill_gap = None
        tailored_resume = None
        context_mode = "general"
        requirement_source = "No verified role requirements are available yet."
        match_job = None

        if job:
            context_mode = "selected_job"
            requirement_source = "Selected synchronized CareerAI job"
            match_job = job
            match = compute_match(candidate.get("skills", []), job)
            skill_gap = self._cached_skill_gap(candidate, job)
            tailored_resume = resume_agent.load_cached_resume(
                self.db, self.user_id, normalized_job_id
            )
        elif pasted_jd:
            context_mode = "pasted_jd"
            requirement_source = "User-provided pasted job description"
            mentions = career_assistant_agent.extract_skill_mentions(pasted_jd)
            match_job = {
                "title": target_role or "Pasted job description",
                "required_skills": ", ".join(mentions),
                "preferred_skills": "",
                "description": pasted_jd,
            }
            match = compute_match(candidate.get("skills", []), match_job)
        elif target_role:
            context_mode = "target_role"
            requirement_source = "General target-role guidance; not a verified job description"
            if role_hints:
                match_job = {
                    "title": target_role,
                    "required_skills": ", ".join(role_hints),
                    "preferred_skills": "",
                    "description": "General target-role learning context.",
                }
                match = compute_match(candidate.get("skills", []), match_job)

        try:
            interview = {
                "questions": interview_agent.list_recent_questions(
                    self.db, self.user_id, limit=5
                ),
                "plans": interview_agent.list_recent_plans(
                    self.db, self.user_id, limit=3
                ),
            }
        except Exception:
            interview = {"questions": [], "plans": []}

        applications = []
        try:
            with self.db.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT a.status, j.job_id, j.title, j.company, a.updated_at
                    FROM applications a
                    JOIN jobs j ON j.job_id = a.job_id
                    WHERE a.user_id = %s
                    ORDER BY a.updated_at DESC, a.id DESC
                    LIMIT 5
                    """,
                    (self.user_id,),
                )
                applications = cursor.fetchall()
        except Exception:
            applications = []

        return {
            "candidate": candidate,
            "job": job,
            "match": match,
            "match_job": match_job,
            "skill_gap": skill_gap,
            "tailored_resume": tailored_resume,
            "interview": interview,
            "applications": applications,
            "pasted_jd": pasted_jd,
            "target_role": target_role,
            "role_hints": role_hints,
            "context_mode": context_mode,
            "requirement_source": requirement_source,
            "job_id": normalized_job_id,
            "conversation_history": history or [],
        }

    def _assistant_session(self, session_id: int | None = None) -> dict:
        if session_id not in (None, ""):
            normalized = self._assistant_positive_id(session_id, "session_id")
            row = career_assistant_agent.get_session(self.db, self.user_id, normalized)
            if row is None:
                raise career_assistant_agent.ChatSessionNotFound(
                    "Conversation was not found for this user."
                )
            self._restore_selected_job_context(row, normalized)
            return row
        row = career_assistant_agent.get_latest_session(self.db, self.user_id)
        if row is not None:
            self._restore_selected_job_context(row, int(row["id"]))
            return row
        session_id = career_assistant_agent.create_session(
            self.db, self.user_id, {"job_id": None, "target_role": "", "pasted_jd": ""}
        )
        row = career_assistant_agent.get_session(self.db, self.user_id, session_id)
        self._restore_selected_job_context(row, int(session_id))
        return row

    def _restore_selected_job_context(self, row: dict, normalized_session_id: int) -> None:
        """Recover a selected job from chat_context for older/UI-created sessions."""
        context = row.get("context") or {}
        if context.get("job_id"):
            return
        try:
            with self.db.cursor() as cursor:
                cursor.execute(
                    "SELECT current_job_id FROM chat_context WHERE session_id = %s",
                    (normalized_session_id,),
                )
                context_row = cursor.fetchone()
            if context_row and context_row.get("current_job_id"):
                context["job_id"] = int(context_row["current_job_id"])
                row["context"] = context
        except Exception:
            logger.exception("Could not load Assistant selected-job context")

    def run_career_assistant(
        self,
        message: str,
        job_id: int | None = None,
        target_role: str = "",
        pasted_jd: str = "",
        session_id: int | None = None,
    ) -> dict:
        """Run a grounded assistant turn and persist both messages."""
        message = str(message or "").strip()
        if not message:
            raise ValueError("A question is required.")
        if len(message) > 4000:
            raise ValueError("Question must be 4000 characters or fewer.")
        session = self._assistant_session(session_id)
        stored_context = session.get("context") or {}
        if job_id in (None, ""):
            job_id = stored_context.get("job_id")
        if not target_role:
            target_role = stored_context.get("target_role", "")
        if not pasted_jd:
            pasted_jd = stored_context.get("pasted_jd", "")
        history = career_assistant_agent.compact_history(
            career_assistant_agent.list_messages(self.db, self.user_id, session["id"])
        )
        context = self._assistant_context(
            message,
            job_id=job_id,
            target_role=target_role,
            pasted_jd=pasted_jd,
            history=history,
        )
        result = career_assistant_agent.answer_question(message, context)
        career_assistant_agent.append_message(
            self.db, self.user_id, session["id"], "user", message, result["intent"]
        )
        career_assistant_agent.append_message(
            self.db, self.user_id, session["id"], "assistant", result["answer"], result["intent"]
        )
        career_assistant_agent.update_session_context(
            self.db,
            self.user_id,
            session["id"],
            {
                "job_id": context.get("job_id"),
                "target_role": context.get("target_role", ""),
                "pasted_jd": context.get("pasted_jd", ""),
                "context_mode": context.get("context_mode", "general"),
            },
        )
        return {
            **result,
            "session_id": session["id"],
            "messages": career_assistant_agent.list_messages(
                self.db, self.user_id, session["id"]
            ),
            "context": {
                "mode": context.get("context_mode", "general"),
                "job_id": context.get("job_id"),
                "target_role": context.get("target_role", ""),
                "requirement_source": context.get("requirement_source", ""),
            },
        }

    def get_assistant_session(self, session_id: int | None = None) -> dict:
        session = self._assistant_session(session_id)
        return {
            "session_id": session["id"],
            "context": session.get("context") or {},
            "messages": career_assistant_agent.list_messages(
                self.db, self.user_id, session["id"]
            ),
        }

    def reset_career_assistant(self) -> dict:
        session_id = career_assistant_agent.create_session(
            self.db, self.user_id, {"job_id": None, "target_role": "", "pasted_jd": ""}
        )
        return {"session_id": session_id, "context": {}, "messages": []}
