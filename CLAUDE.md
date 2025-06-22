# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Environment Setup
```bash
# Install dependencies using standard pip or uv (if available)
pip install -e .

# Install development dependencies
pip install -e .[dev]

# Using uv (if available, faster)
uv sync --dev
```

### Testing
```bash
# Run all tests
pytest

# Run specific test categories using markers
pytest -m unit        # Unit tests only
pytest -m integration # Integration tests only
pytest -m gui         # GUI tests only
pytest -m slow        # Slow tests only

# Run single test file
pytest tests/unit/test_tag_search.py

# Run with coverage
pytest --cov=src --cov-report=xml
pytest --cov=src --cov-report=html
```

### Code Quality
```bash
# Run linting and formatting
ruff check
ruff format

# Run type checking
mypy src/
```

### Application Usage
```bash
# Launch GUI application
tag-db

# Run as Python module
python -m genai_tag_db_tools

# Library usage example
python -c "from genai_tag_db_tools.services.tag_search import TagSearchService; print('Available')"
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
- `services/tag_management.py` - Tag CRUD operations and validation
- `services/tag_search.py` - Advanced search and filtering capabilities
- `services/tag_statistics.py` - Usage analytics and reporting
- `services/import_data.py` - Data import from various sources

**GUI Layer:**
- `gui/windows/main_window.py` - Primary application window
- `gui/widgets/` - Modular widget components for specific functionality
- `gui/designer/` - Qt Designer UI files and generated Python code

### Database Schema

The database uses a sophisticated multi-table schema designed for comprehensive tag management:

**Core Tables:**
- `TAGS` - Primary tag storage with metadata
- `TAG_TRANSLATIONS` - Multi-language translation support
- `TAG_FORMATS` - Platform-specific format definitions (Danbooru, E621, etc.)
- `TAG_STATUS` - Tag state management and relationships
- `TAG_USAGE_COUNTS` - Usage frequency tracking per format

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
from genai_tag_db_tools.services.tag_search import TagSearchService
from genai_tag_db_tools.services.tag_management import TagManagementService

# Initialize services with database path
search_service = TagSearchService("path/to/tags.db")
management_service = TagManagementService("path/to/tags.db")

# Search tags
results = search_service.search_tags("landscape")

# Register new tag
new_tag = management_service.register_tag("new_tag", "source_tag")
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

This documentation provides comprehensive guidance for developing and maintaining the genai-tag-db-tools application while ensuring high performance, reliability, and integration capabilities.