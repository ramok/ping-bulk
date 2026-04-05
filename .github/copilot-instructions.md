# Copilot Instructions for ping-bulk

## Allowed Tools and Permissions

This project allows Copilot to use the following tools without additional approval:

### File Operations
- `view` - Read files and directories
- `edit` - Modify existing files
- `create` - Create new files
- `grep` - Search file contents
- `glob` - Find files by pattern

### Development Tools
- `bash` - Execute shell commands including:
  - `git` - Version control operations
  - `pytest` - Run test suite (with `-n auto` for parallel execution)
  - `python3` - Run Python scripts and debugging
  - Standard Unix tools: `ls`, `grep`, `find`, `cat`, `head`, `tail`, `wc`, etc.
- `sql` - Use SQLite for session state tracking

### Code Intelligence
- LSP tools (when available) for code navigation

### Information & Documentation
- `fetch_copilot_cli_documentation` - Access Copilot CLI documentation
- `web_search` - Search the web for current information (pricing, documentation, etc.)

### User Interaction
- `ask_user` - Ask clarifying questions during task execution

### GitHub Integration
- GitHub MCP server tools for repository operations (commits, PRs, issues, etc.)

## Working Directory
- Allowed: Repository root (`$HOME/work/github/ping-bulk.git`) and all subdirectories

## Standard Workflow

When starting a new session:
1. Agent reads this file to understand allowed tools
2. User approves the listed tools when prompted
3. If new tools are needed, update this file after approval

## Safety Guidelines

**Destructive Commands Require Confirmation:**
Before executing any destructive or irreversible commands, always use `ask_user` to get explicit confirmation:
- File deletion: `rm`, `rm -rf`
- Git operations: `git reset --hard`, `git push --force`, `git clean`, `git rebase`
- Data modification: `truncate`, `dd`, `shred`
- Process termination: `kill -9`, `killall`
- Permission changes that affect security: `chmod 777`, `chown`

For routine operations (git add, git commit, pytest runs, file edits), confirmation is not required.

## Git Commit Guidelines

- **Do NOT add** `Co-authored-by: Copilot <...>` trailers to commit messages
- Follow the commit message format described in `AGENTS.md` (UX-focused, concise)
- Always use `git add <specific-file>` - never `git add .` or `git commit -a`

## Project-Specific Guidelines

See `AGENTS.md` for detailed project architecture and development guidelines.
