# Branching Strategy

## Branch Roles

- `main`: production and final stable branch.
- `dev`: integration branch for the next release.
- `feat-<number>`: feature work branch, for example `feat-001`, `feat-002`.

## New Work Flow

Always create a feature branch from the latest `dev`.

```powershell
git switch dev
git pull --rebase origin dev
git switch -c feat-001
```

Use the next available feature number. Keep the same feature branch number across frontend and backend when both repositories are changed for one task.

## Before Merging Into Dev

Rebase the feature branch on top of the latest `dev` before opening or merging the pull request.

```powershell
git switch dev
git pull --rebase origin dev
git switch feat-001
git rebase dev
```

If the branch was already pushed before rebasing, update the remote branch with:

```powershell
git push --force-with-lease origin feat-001
```

## Merge Rule

Merge feature branches into `dev` with a linear history. Avoid merge commits so the Git graph stays easy to read and rollback remains straightforward.

Preferred merge style:

```powershell
git switch dev
git pull --rebase origin dev
git merge --ff-only feat-001
git push origin dev
```

If fast-forward is not possible, rebase the feature branch on `dev` again before merging.

## Release Flow

After `dev` is tested and ready, release it into `main`.

Before merging, rebase `dev` on top of the latest `main`.

```powershell
git switch main
git pull --rebase origin main
git switch dev
git pull --rebase origin dev
git rebase main
```

Then squash the release into one commit on `main`.

```powershell
git switch main
git merge --squash dev
git commit -m "chore: dev 변경사항을 main에 반영"
git push origin main
```

## Commit Message Rule

Write commit messages in Korean with one short line describing what changed.

Format:

```text
type: 변경 내용
```

Allowed types:

- `feat`: 새로운 기능 추가
- `fix`: 버그 수정
- `docs`: 문서 수정
- `style`: 코드 포맷팅, 세미콜론 누락, 코드 변경이 없는 경우
- `refactor`: 코드 리팩토링
- `test`: 테스트 코드, 리팩토링 테스트 코드 추가
- `chore`: 빌드 업무 수정, 패키지 매니저 수정

Examples:

```text
feat: 맛집 검색 API를 추가
fix: 로그인 토큰 만료 오류를 수정
docs: 브랜치 전략 문서를 추가
refactor: 사용자 인증 로직을 분리
chore: 프론트엔드 패키지 버전을 정리
```
