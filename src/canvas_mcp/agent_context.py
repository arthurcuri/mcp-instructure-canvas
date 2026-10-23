"""Small private assignment references; never a source of submission authorization."""

import re
from urllib.parse import urlsplit


def assignment_links(text: str, api_url: str) -> list[dict]:
    origin = urlsplit(api_url)
    references = {}
    for candidate in re.findall(r'https://[^\s<>\[\]"\']+', text):
        try:
            url = urlsplit(candidate.rstrip(".,;!?)"))
            if (
                (url.scheme, url.hostname, url.port or 443)
                != (origin.scheme, origin.hostname, origin.port or 443)
                or url.username
                or url.password
            ):
                continue
        except ValueError:
            continue
        match = re.fullmatch(
            r"/courses/([1-9][0-9]{0,18})/assignments/([1-9][0-9]{0,18})/?", url.path
        )
        if match:
            course, assignment = map(int, match.groups())
            references[course, assignment] = {
                "course_id": course,
                "assignment_id": assignment,
                "url": f"{origin.scheme}://{origin.netloc}/courses/{course}/assignments/{assignment}",
            }
    return list(references.values())


def refers_to_reminder(text: str) -> bool:
    return bool(
        re.search(
            r"\b(?:ess[ae]|est[ae]|aquel[ae])\s+(?:atividade|tarefa|trabalho)\b"
            r"|\b(?:atividade|tarefa|trabalho)\s+(?:acima|do lembrete)\b",
            text,
            re.IGNORECASE,
        )
    )
