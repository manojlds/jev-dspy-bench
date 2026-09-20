from jev_dspy_bench.state import build_state, parse_patch, serialize_state

PATCH = """diff --git a/access.ts b/access.ts
--- a/access.ts
+++ b/access.ts
@@ -1,2 +1,2 @@
-const allowed = user.isAdmin;
+const allowed = !user.isAdmin;
 export { allowed };
"""


def test_builds_canonical_drs_state() -> None:
    files = parse_patch(PATCH)
    assert files[0].filename == "access.ts"
    assert files[0].patch == (
        "@@ -1,2 +1,2 @@\n-const allowed = user.isAdmin;\n"
        "+const allowed = !user.isAdmin;\n export { allowed };"
    )

    state = build_state(PATCH)
    assert state.repositoryContext == "{}"
    assert "### access.ts" in state.diff
    assert serialize_state(state).startswith('{"task":')
    assert "repositoryContext" in serialize_state(state)


def test_deleted_files_match_drs_quality_behavior() -> None:
    patch = """diff --git a/old.ts b/old.ts
--- a/old.ts
+++ /dev/null
@@ -1,1 +0,0 @@
-removed()
"""
    state = build_state(patch)
    assert state.diff == "No inline diff content is available for this review."
