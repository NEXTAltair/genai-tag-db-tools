# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Important Instructions
Do what has been asked; nothing more, nothing less.
NEVER create files unless they're absolutely necessary for achieving your goal.
ALWAYS prefer editing an existing file to creating a new one.
NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.

## Development Commands

### Environment Setup

#### Cross-Platform Environment Management

This project supports Windows/Linux environments with independent virtual environments to manage platform-specific dependencies properly.

```bash
# Automatic OS detection setup (recommended)
./scripts/setup.sh

# Manual environment specification
UV_PROJECT_ENVIRONMENT=.venv_linux uv sync --dev     # Linux
$env:UV_PROJECT_ENVIRONMENT=".venv_windows"; uv sync --dev  # Windows

# Traditional single environment
uv sync --dev

# Add new dependencies
uv add package-name

# Add development dependencies
uv add --dev package-name
```

### Running the Application

#### Cross-Platform Execution

```bash
# Windows Environment
$env:UV_PROJECT_ENVIRONMENT = ".venv_windows"; uv run tag-db

# Linux Environment  
UV_PROJECT_ENVIRONMENT=.venv_linux uv run tag-db

# Using Makefile (all platforms)
make run-gui

# Traditional single environment
uv run tag-db

# Alternative module execution
uv run python -m genai_tag_db_tools.main
```

### Development Tools
```bash
# Run tests
pytest

# Run specific test categories
pytest -m unit        # Unit tests only
pytest -m integration # Integration tests only
pytest -m gui         # GUI tests only (headless in dev container)

# For GUI tests in cross-platform environments (headless in Linux/container)

# Run linting and formatting
ruff check
ruff format

# Run type checking
mypy src/

# Check test coverage
pytest --cov=src --cov-report=html

# Run single test file
pytest tests/path/to/test_file.py
```

### Application Usage
```bash
# Launch GUI application
tag-db

# Run as Python module
python -m genai_tag_db_tools

# Library usage example
python -c "from genai_tag_db_tools.services.tag_search import TagSearcher; print('Available')"
```

## Project Architecture

### Core Design Pattern: Service-Repository-GUI Architecture

The application follows a clean 3-layer architecture optimized for database-centric tag management:

1. **Repository Layer** (`data/`) - Database access and ORM management
2. **Service Layer** (`services/`) - Business logic and transaction management  
3. **GUI Layer** (`gui/`) - User interface and presentation logic

### Key Components

**Entry Points:**
- `main.py` - Primary application launcher for GUI
- CLI command `tag-db` - Direct application access
- Module import - Library usage for external projects

**Database Layer:**
- `data/database_schema.py` - SQLAlchemy models and relationships
- `data/tag_repository.py` - Data access patterns and queries
- `data/tags_v*.db` - SQLite database files with tag data

**Service Layer:**
- `services/app_services.py` - GUI service wrappers with Qt signals
- `services/tag_search.py` - Core search logic with TagSearcher class
- `services/tag_statistics.py` - Statistics computation and analytics
- `services/import_data.py` - Data import from various sources
- `services/tag_register.py` - Tag registration and validation logic
- `services/polars_schema.py` - Polars DataFrame schemas for data processing

**GUI Layer:**
- `gui/windows/main_window.py` - Primary application window
- `gui/widgets/` - Modular widget components for specific functionality
- `gui/designer/` - Qt Designer UI files and generated Python code

### Database Schema

The database uses a sophisticated multi-table schema designed for comprehensive tag management:

**Core Tables:**
- `TAGS` - Primary tag storage with metadata
- `TAG_TRANSLATIONS` - Multi-language translation support
- `TAG_FORMATS` - Platform-specific format definitions (Danbooru, E621, Derpibooru, etc.)
- `TAG_TYPE_NAME` - Tag type definitions (general, artist, character, etc.)
- `TAG_STATUS` - Tag state management and relationships
- `TAG_USAGE_COUNTS` - Usage frequency tracking per format
- `TAG_TYPE_FORMAT_MAPPING` - Mapping between tag types and formats

**Key Relationships:**
- Tags have multiple translations (one-to-many)
- Tags have format-specific status records (many-to-many via TAG_STATUS)
- Tags can reference preferred tags for alias management
- Usage counts track popularity across different formats

### Key Design Principles

**Database-First Architecture:**
- All operations center around maintaining database integrity
- Complex relationships handled through proper foreign keys
- Performance optimized through strategic indexing

**Performance Optimization:**
- SQLite configured with WAL mode for concurrency
- Strategic indexes for common query patterns
- Polars integration for high-performance bulk operations
- Background threading for GUI responsiveness

**Type Safety:**
- Comprehensive type hints throughout codebase
- SQLAlchemy 2.0 typed relationships
- Generic repository patterns with type safety

### External Integration

**Library Usage Pattern:**
```python
from genai_tag_db_tools.services.tag_search import TagSearcher
from genai_tag_db_tools.services.app_services import TagSearchService, TagRegisterService
from genai_tag_db_tools.data.tag_repository import TagRepository

# Initialize core searcher
searcher = TagSearcher()
results = searcher.search_tags("landscape")

# Or use GUI service wrappers (with Qt signals)
search_service = TagSearchService()
register_service = TagRegisterService()

# Repository pattern for direct database access
repository = TagRepository()
tags = repository.search_tags_by_name("landscape")
```

**LoRAIro Integration:**
- Shared database access for tag lookup during image annotation
- Real-time tag suggestions based on usage statistics
- Cross-reference validation for annotation quality

### Configuration Management

**Database Configuration:**
- SQLite optimization with performance pragmas
- Connection pooling for concurrent access
- Migration management through Alembic
- Backup and recovery procedures

**Application Settings:**
- User preferences for GUI layout and behavior
- Search preferences and default filters
- Import/export format preferences
- Language and translation preferences

### Important File Patterns

**Database Files:**
- `tags_v3.db`, `tags_v4.db` - Version-specific tag databases
- Migration scripts in database structure changes
- Backup files with timestamp naming convention

**Configuration Files:**
- `pyproject.toml` - Project configuration and dependencies
- Ruff and mypy configuration for code quality
- pytest configuration with test markers

**GUI Resources:**
- `.ui` files - Qt Designer interface definitions
- `*_ui.py` files - Generated Python code from Designer files
- Custom widgets in `widgets/` directory

### Development Guidelines

**Adding New Features:**
1. Start with database schema changes if needed
2. Implement repository layer methods for data access
3. Add business logic in appropriate service class
4. Create or update GUI components as needed
5. Write comprehensive tests for all layers

**Database Modifications:**
1. Create Alembic migration script
2. Test migration with sample data
3. Update SQLAlchemy models
4. Add appropriate indexes for performance
5. Update repository methods as needed

**Performance Considerations:**
- All database operations should use proper transactions
- Bulk operations should leverage Polars for data processing
- GUI operations should use background threads for responsiveness
- Search operations should be optimized with appropriate indexes

### Testing Strategy

**Test Categories (pytest markers):**
- `unit` - Fast unit tests with mocking for individual components
- `integration` - Database integration tests with test databases
- `gui` - GUI component tests using pytest-qt
- `slow` - Performance and large dataset tests

**Test Structure:**
- `tests/unit/` - Unit tests organized by module
- `tests/gui/` - GUI-specific tests
- `tests/resource/` - Test data and sample files
- `conftest.py` - Shared test fixtures and configuration

### Code Style Guidelines

**Database Operations:**
- Always use repository pattern for data access
- Handle transactions properly with rollback on errors
- Use typed SQLAlchemy models with proper relationships
- Validate inputs before database operations

**Service Layer:**
- Implement comprehensive error handling and validation
- Use dependency injection for repository access
- Maintain transaction boundaries appropriately
- Provide meaningful error messages

**GUI Components:**
- Follow Qt signal/slot patterns for communication
- Use background threads for long-running operations
- Implement proper progress feedback for users
- Handle errors gracefully with user-friendly messages

### Performance Optimization

**Database Performance:**
- Use appropriate indexes for common query patterns
- Leverage SQLite optimization features (WAL, pragmas)
- Implement efficient bulk operations
- Monitor query performance with EXPLAIN QUERY PLAN

**Memory Management:**
- Use lazy loading for large datasets
- Implement proper cleanup for resources
- Monitor memory usage with large tag collections
- Optimize GUI rendering for large result sets

### Error Handling

**Database Errors:**
- Handle connection failures gracefully
- Provide meaningful error messages for constraint violations
- Implement proper transaction rollback on errors
- Log database errors with sufficient context

**Business Logic Errors:**
- Validate inputs comprehensively
- Provide clear error messages for validation failures
- Handle edge cases and boundary conditions
- Implement proper fallback behaviors

## Rule Files and Documentation References

### .cursor Directory Structure
Claude Code should reference these files for development guidance:

**Core Development Rules:**
- `.cursor/rules/rules.mdc` - Master development workflow and architectural rules
- `.cursor/rules/coding-rules.mdc` - Coding standards, type hints, error handling, documentation requirements

**Module-Specific Rules:**
- `.cursor/rules/module_rules/module-database-rules.mdc` - Database operation patterns
- `.cursor/rules/test_rules/testing-rules.mdc` - Test strategy and pytest configuration

### Reference Guidelines for Claude Code

**When Planning (PLAN/Architect Mode):**
1. Reference `.cursor/rules/rules.mdc` for planning guidelines
2. Check existing documentation in `docs/` directory

**When Implementing (ACT/Code Mode):**
1. Follow `.cursor/rules/coding-rules.mdc` for code quality standards
2. Reference module-specific rules for relevant components

**When Testing:**
1. Use guidelines from `.cursor/rules/test_rules/testing-rules.mdc`
2. Ensure coverage requirements are met

**Key Principles:**
- Reference rules before starting any development task
- Follow established patterns and conventions
- Always check for existing solutions in documentation

## Troubleshooting

### Cross-Platform Development Environment

**Environment Isolation:**
- Windows environment: `.venv_windows` - Windows-specific dependencies and binaries
- Linux environment: `.venv_linux` - Linux-specific dependencies and binaries  
- Independent GUI operation support for both environments

**Development Workflow:**
```bash
# Setup using unified script (automatic OS detection)
./scripts/setup.sh

# Linux/Container environment - development and testing
UV_PROJECT_ENVIRONMENT=.venv_linux uv run pytest

# Windows environment - execution and GUI verification
$env:UV_PROJECT_ENVIRONMENT = ".venv_windows"; uv run tag-db

# Unified execution using Makefile
make run-gui  # Automatically selects appropriate environment
```

**GUI Testing Notes:**
- Linux environment: Headless execution (pytest-qt + QT_QPA_PLATFORM=offscreen)
- Windows environment: Native GUI window display
- Cross-platform test compatibility guaranteed

This documentation provides comprehensive guidance for developing and maintaining the genai-tag-db-tools application while ensuring high performance, reliability, and integration capabilities.