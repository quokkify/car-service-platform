#!/usr/bin/env bash
set -euo pipefail

ref="${TEMPLATE_REF:-}"
if [[ -z "$ref" ]]; then
  ref="$(gh release view --repo quokkify/project-toolkit --json tagName --jq .tagName)"
fi
if [[ ! "$ref" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Ref must be an exact released project-toolkit tag: $ref" >&2
  exit 2
fi
release="$(gh release view "$ref" --repo quokkify/project-toolkit \
  --json tagName,isDraft,isPrerelease,publishedAt)"
if [[ "$(jq -r '.tagName' <<<"$release")" != "$ref" || \
  "$(jq -r '.isDraft' <<<"$release")" != "false" || \
  "$(jq -r '.isPrerelease' <<<"$release")" != "false" || \
  "$(jq -r '.publishedAt // empty' <<<"$release")" == "" ]]; then
  echo "Ref must identify a published, non-draft, non-prerelease release: $ref" >&2
  exit 2
fi
echo "Updating to project-toolkit $ref"

git switch -C "$BRANCH"
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
copier update --trust --defaults --conflict=rej --skip-tasks --vcs-ref "$ref" --data "toolkit_version=$ref" .

mapfile -t rejected < <(find . -name '*.rej' -not -path './.git/*' -print)
if (( ${#rejected[@]} )); then
  printf 'Copier produced conflict files:\n' >&2
  printf '  %s\n' "${rejected[@]}" >&2
  exit 1
fi

# Stage before the no-op check so Copier-created untracked files are included.
git add --all
if git diff --cached --quiet; then
  printf 'Already up to date with %s; nothing to push.\n' "$ref" >> "$GITHUB_STEP_SUMMARY"
  exit 0
fi

git diff --cached --check
git commit -m "chore(template): update shared project template"
remote="$(git ls-remote --heads origin "refs/heads/$BRANCH" | cut -f1)"
if [[ -n "$remote" ]]; then
  git push "--force-with-lease=refs/heads/$BRANCH:$remote" origin "HEAD:refs/heads/$BRANCH"
else
  git push origin "HEAD:refs/heads/$BRANCH"
fi

{
  printf '## Template update ready\n\n'
  printf 'Updated to %s and pushed %s.\n\n' "$ref" "$BRANCH"
  printf 'Open the pull request yourself so pull_request checks run:\n\n'
  printf '%s/%s/compare/%s...%s?expand=1\n' \
    "$GITHUB_SERVER_URL" "$GITHUB_REPOSITORY" "$DEFAULT_BRANCH" "$BRANCH"
} >> "$GITHUB_STEP_SUMMARY"
