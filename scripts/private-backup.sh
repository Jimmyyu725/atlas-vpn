#!/usr/bin/env bash
set -euo pipefail
set +x

backup_branch=$(git branch --show-current)
if [[ -z "$backup_branch" ]]; then
  printf '%s\n' '停止：detached HEAD 没有可备份的当前分支。' >&2
  exit 1
fi
backup_ref="refs/heads/$backup_branch"
if ! git check-ref-format "$backup_ref" >/dev/null 2>&1; then
  printf '%s\n' '停止：当前分支不能映射为安全的远程 ref。' >&2
  exit 1
fi
backup_local_hash=$(git rev-parse --verify "HEAD^{commit}")

mapfile -t backup_push_urls < <(git remote get-url --push --all origin 2>/dev/null)
if (( ${#backup_push_urls[@]} != 1 )) || [[ -z "${backup_push_urls[0]}" ]]; then
  printf '%s\n' '停止：origin 必须恰好有一个非空、可验证的实际 push 目标。' >&2
  exit 1
fi
backup_push_url=${backup_push_urls[0]}
unset backup_push_urls

case "$backup_push_url" in
  git@github.com:*) backup_repo=${backup_push_url#git@github.com:} ;;
  ssh://git@github.com/*) backup_repo=${backup_push_url#ssh://git@github.com/} ;;
  https://github.com/*) backup_repo=${backup_push_url#https://github.com/} ;;
  https://*@*) printf '%s\n' '停止：HTTPS push 目标不得包含 credential-bearing userinfo。' >&2; unset backup_push_url; exit 1 ;;
  *) printf '%s\n' '停止：实际 push 目标无法唯一映射到 GitHub 仓库。' >&2; exit 1 ;;
esac
backup_repo=${backup_repo%.git}
if [[ ! "$backup_repo" =~ ^[^/[:space:]]+/[^/[:space:]]+$ ]]; then
  printf '%s\n' '停止：实际 push 目标不是唯一的 owner/repository。' >&2
  exit 1
fi

backup_repo_meta=$(
  gh repo view "$backup_repo" --json visibility,nameWithOwner,url \
    --jq '[.visibility, .nameWithOwner, .url] | @tsv' 2>/dev/null
) || { printf '%s\n' '停止：无法查询实际 push 仓库。' >&2; exit 1; }
IFS=$'\t' read -r backup_visibility backup_canonical backup_web_url <<<"$backup_repo_meta"
unset backup_repo_meta
if [[ "$backup_visibility" != "PRIVATE" || \
      "${backup_canonical,,}" != "${backup_repo,,}" || \
      "${backup_web_url,,}" != "https://github.com/${backup_canonical,,}" ]]; then
  printf '%s\n' '停止：实际 push 目标未被明确验证为对应的 PRIVATE GitHub 仓库。' >&2
  exit 1
fi

backup_transport_token=$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')
if [[ ! "$backup_transport_token" =~ ^[0-9a-f]{32}$ ]]; then
  printf '%s\n' '停止：无法生成安全的临时 transport alias。' >&2
  unset backup_push_url backup_transport_token
  exit 1
fi
backup_transport_alias="codex-verified-${backup_local_hash}-${backup_transport_token}:"
unset backup_transport_token

if [[ "$backup_local_hash" != "$(git rev-parse --verify 'HEAD^{commit}')" ]]; then
  printf '%s\n' '停止：mutation 前本地 HEAD 已偏离已验收提交。' >&2
  unset backup_transport_alias backup_push_url
  exit 1
fi
git -c "url.${backup_push_url}.insteadOf=${backup_transport_alias}" \
    -c "url.${backup_push_url}.pushInsteadOf=${backup_transport_alias}" \
    push "$backup_transport_alias" "$backup_local_hash:$backup_ref" >/dev/null 2>&1
backup_push_status=$?
printf 'private backup push exit=%s\n' "$backup_push_status"
if (( backup_push_status != 0 )); then
  unset backup_transport_alias backup_push_url
  exit 1
fi

backup_remote_line=$(
  git -c "url.${backup_push_url}.insteadOf=${backup_transport_alias}" \
      -c "url.${backup_push_url}.pushInsteadOf=${backup_transport_alias}" \
      ls-remote --exit-code "$backup_transport_alias" "$backup_ref" 2>/dev/null
) || { printf '%s\n' '停止：无法从实际 push 目标读取精确分支。' >&2; unset backup_transport_alias backup_push_url; exit 1; }
backup_remote_hash=${backup_remote_line%%[[:space:]]*}
unset backup_remote_line backup_transport_alias backup_push_url
if [[ -z "$backup_remote_hash" || "$backup_local_hash" != "$backup_remote_hash" ]]; then
  printf '%s\n' '停止：本地与实际 push 目标的提交哈希不一致。' >&2
  exit 1
fi
backup_current_hash=$(git rev-parse --verify "HEAD^{commit}")
if [[ "$backup_current_hash" == "$backup_local_hash" ]]; then
  printf '私有备份已验证：仓库=%s 分支=%s captured=%s remote=%s match=yes current-head=covered\n' \
    "$backup_canonical" "$backup_branch" "$backup_local_hash" "$backup_remote_hash"
else
  printf '私有备份已验证：仓库=%s 分支=%s captured=%s remote=%s match=yes；当前 HEAD 已变化，本次备份不覆盖当前 HEAD。\n' \
    "$backup_canonical" "$backup_branch" "$backup_local_hash" "$backup_remote_hash"
fi
