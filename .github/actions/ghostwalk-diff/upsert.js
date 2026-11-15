// Post ONE pull-request comment and update it in place on every push. Never duplicates: the comment is found by its hidden marker.
// Used by action.yml through actions/github-script, and unit-tested with a fake `github` object (tests/test_action.py).
const MARKER = "<!-- ghostwalk-diff -->"

module.exports = async function upsert({ github, context, body }) {
  if (!body.includes(MARKER)) throw new Error("comment body has no ghostwalk marker")
  const { owner, repo } = context.repo
  const issue_number = context.issue.number
  const comments = await github.paginate(github.rest.issues.listComments, { owner, repo, issue_number, per_page: 100 })
  const mine = comments.filter((c) => c.body && c.body.includes(MARKER))
  if (mine.length === 0) {
    const r = await github.rest.issues.createComment({ owner, repo, issue_number, body })
    return { action: "created", id: r.data.id }
  }
  const [keep, ...extras] = mine.sort((a, b) => a.id - b.id)
  for (const dup of extras) await github.rest.issues.deleteComment({ owner, repo, comment_id: dup.id })   // heal an earlier duplicate
  if (keep.body === body) return { action: "unchanged", id: keep.id }
  await github.rest.issues.updateComment({ owner, repo, comment_id: keep.id, body })
  return { action: "updated", id: keep.id }
}
