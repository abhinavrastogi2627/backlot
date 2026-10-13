"""Repository issue labels, as measured beside ``github.list_issues``."""

from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

from tests._helpers import complete, corpus_client, tok


@pytest.fixture
def labelled_issues(tmp_path):
    rows = [
        ("Bug", ["bug"], "issue", "public", "bob@acme.com"),
        ("Docs", ["documentation"], "issue", "public", "bob@acme.com"),
        ("Fix", ["BUG", "Documentation"], "pull_request", "public", "bob@acme.com"),
        ("Private bug", ["bug"], "issue", "private", "hana@acme.com"),
        ("Source", ["bug"], "file", "public", "bob@acme.com"),
    ]
    records = [
        complete(
            "github",
            doc_id=f"label-{index}",
            repo="triage",
            title=title,
            labels=labels,
            subtype=kind,
            visibility=visibility,
            author_email=author,
            state="open",
            **({"path": "src/main.py"} if kind == "file" else {}),
        )
        for index, (title, labels, kind, visibility, author) in enumerate(rows)
    ]
    with corpus_client(tmp_path, records) as (client, settings):
        tokens = yaml.safe_load(settings.tokens_path.read_text())
        yield (
            client,
            {"Authorization": f"Bearer {settings.admin_token}"},
            {"Authorization": f"Bearer {tok(tokens, 'bob@acme.com')}"},
        )


@pytest.mark.parametrize(
    "labels, titles",
    [
        ("", {"Bug", "Docs", "Fix", "Private bug"}),
        ("bug", {"Bug", "Fix", "Private bug"}),
        ("BUG", {"Bug", "Fix", "Private bug"}),
        ("documentation", {"Docs", "Fix"}),
        ("bug,documentation", {"Fix"}),
        ("Documentation,Bug", {"Fix"}),
        ("bug,bug", {"Bug", "Fix", "Private bug"}),
        ("bug,", {"Bug", "Fix", "Private bug"}),
        (",", {"Bug", "Docs", "Fix", "Private bug"}),
        (",,", {"Bug", "Docs", "Fix", "Private bug"}),
        (" ", {"Bug", "Docs", "Fix", "Private bug"}),
        ("\t", {"Bug", "Docs", "Fix", "Private bug"}),
        ("\u00a0", {"Bug", "Docs", "Fix", "Private bug"}),
        ("\x1c", set()),
        (" ,", set()),
        ("zzqq-no-such-label", set()),
        ("bug,zzqq-no-such-label", set()),
        (" bug", set()),
        ("bug, documentation", set()),
        ("bug,,documentation", set()),
    ],
)
def test_repository_issues_match_every_named_label(labelled_issues, labels, titles):
    client, admin, _ = labelled_issues
    response = client.get(
        "/github/repos/acme/triage/issues", headers=admin, params={"labels": labels}
    )
    assert response.status_code == 200
    assert {row["title"] for row in response.json()} == titles


def test_only_the_last_repeated_labels_parameter_is_read(labelled_issues):
    client, admin, _ = labelled_issues
    response = client.get(
        "/github/repos/acme/triage/issues?labels=bug&labels=documentation", headers=admin
    )
    assert response.status_code == 200
    assert {row["title"] for row in response.json()} == {"Docs", "Fix"}


def test_label_filter_keeps_scoped_visibility(labelled_issues):
    client, _, scoped = labelled_issues
    response = client.get("/github/repos/acme/triage/issues?labels=bug", headers=scoped)
    assert response.status_code == 200
    assert {row["title"] for row in response.json()} == {"Bug", "Fix"}


def test_label_filter_runs_before_pagination_and_survives_in_links(labelled_issues):
    client, admin, _ = labelled_issues
    response = client.get("/github/repos/acme/triage/issues?labels=BUG&per_page=1", headers=admin)
    seen = []
    while True:
        assert response.status_code == 200
        seen.extend(row["title"] for row in response.json())
        next_url = response.links.get("next", {}).get("url")
        if next_url is None:
            break
        assert parse_qs(urlsplit(next_url).query)["labels"] == ["BUG"]
        response = client.get(next_url, headers=admin)
    assert len(seen) == 3
    assert set(seen) == {"Bug", "Fix", "Private bug"}


def test_issue_listing_declares_the_labels_parameter(client):
    operation = client.get("/openapi.json").json()["paths"]["/github/repos/{owner}/{repo}/issues"][
        "get"
    ]
    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    assert parameters["labels"]["schema"]["type"] == "string"
