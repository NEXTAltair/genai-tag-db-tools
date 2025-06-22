# genai-tag-db-tools Technical Specification

## Technology Stack

### Core Technologies

#### Programming Language
- **Python 3.12+**: Modern Python with advanced type features
  - Advanced type hints and generic support
  - Pattern matching and structural pattern matching
  - Dataclass enhancements and frozen classes
  - Exception groups and improved error handling

#### Database Technology
- **SQLite**: Embedded database for portability and performance
  - ACID compliance for data integrity
  - Full-text search capabilities
  - JSON support for flexible data structures
  - WAL mode for improved concurrency
- **SQLAlchemy 2.0+**: Modern ORM with advanced features
  - Declarative base with modern syntax
  - Async support for non-blocking operations
  - Advanced relationship management
  - Query optimization and lazy loading
- **Alembic**: Database migration management
  - Version-controlled schema changes
  - Automatic migration generation
  - Cross-database compatibility
  - Rollback and upgrade procedures

#### GUI Framework
- **PySide6**: Qt for Python with modern features
  - Advanced widget system and layouts
  - Signal/slot communication mechanism
  - Multi-threading support for responsive UI
  - Cross-platform compatibility
- **superqt**: PySide6 extensions for enhanced functionality
  - Additional widgets and utilities
  - Improved threading support
  - Enhanced data visualization components

#### Data Processing
- **Polars**: High-performance data processing
  - Memory-efficient operations for large datasets
  - Lazy evaluation for optimized processing
  - Advanced filtering and aggregation
  - Integration with pandas ecosystem

### Development Tools

#### Code Quality
- **Ruff**: Fast Python linter and formatter
  - Comprehensive rule set for code quality
  - Automatic code fixing capabilities
  - Fast execution with Rust implementation
  - Configurable rules and exclusions
- **mypy**: Static type checking
  - Advanced type inference and validation
  - Generic type support
  - Plugin system for framework integration
  - IDE integration for real-time checking

#### Testing Framework
- **pytest**: Advanced testing framework
  - Fixture-based test organization
  - Parametrized testing capabilities
  - Plugin ecosystem for extensions
  - Detailed test reporting
- **pytest-cov**: Code coverage analysis
  - Line and branch coverage reporting
  - HTML and XML output formats
  - Coverage threshold enforcement
  - Integration with CI/CD pipelines
- **pytest-qt**: GUI testing support
  - Qt application testing capabilities
  - Event simulation and validation
  - Widget interaction testing
  - Async testing support

## Development Environment

### System Requirements

#### Operating System Support
- **Windows 11**: Primary development and testing platform
- **Windows 10**: Supported with full functionality
- **macOS 10.15+**: Supported with Qt compatibility
- **Linux Ubuntu 20.04+**: Supported with package manager integration

#### Hardware Requirements
- **Memory**: 4GB RAM minimum, 8GB recommended for large datasets
- **Storage**: 1GB available space for application and sample data
- **CPU**: Multi-core processor recommended for data processing
- **Display**: 1280x720 minimum resolution for GUI operation

#### Python Environment Requirements
- **Python 3.12 or higher**
- **Virtual environment support** (venv, conda, uv)
- **Package compilation tools** for native dependencies
- **SQLite 3.35+** for advanced database features

### Environment Setup

#### Development Installation
```bash
# Clone repository
git clone https://github.com/NEXTAltair/genai-tag-db-tools.git
cd genai-tag-db-tools

# Create virtual environment (using uv if available)
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install development dependencies
uv sync --dev

# Verify installation
python -c "import genai_tag_db_tools; print('Installation successful')"
```

#### Production Installation
```bash
# Install from PyPI
pip install genai-tag-db-tools

# Install from source
pip install git+https://github.com/NEXTAltair/genai-tag-db-tools.git

# Verify installation
tag-db --version
```

### Configuration Management

#### Project Configuration (`pyproject.toml`)
```toml
[project]
name = "genai-tag-db-tools"
version = "0.2.2"
description = "AI生成画像のタグ管理ツール"
requires-python = ">=3.12"
license = { text = "MIT" }

dependencies = [
    "PySide6>=6.8.0.2",
    "superqt>=0.6.7",
    "polars[all]>=1.9.0",
    "alembic>=1.13.1",
    "sqlalchemy>=2.0.0",
]

[project.scripts]
tag-db = "genai_tag_db_tools.main:main"

[tool.ruff]
line-length = 108
target-version = "py312"
fix = true

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = ["-v", "-s", "--cov=src", "--cov-report=xml"]
markers = [
    "unit: Unit tests",
    "integration: Integration tests", 
    "gui: GUI tests",
    "slow: Tests that take more time",
]
```

#### Database Configuration
```python
# Database connection settings
DATABASE_CONFIG = {
    'echo': False,  # Set to True for SQL query logging
    'pool_pre_ping': True,  # Verify connections before use
    'connect_args': {
        'check_same_thread': False,  # Allow multi-threading
        'timeout': 30,  # Connection timeout in seconds
    }
}

# Performance optimization settings
SQLITE_PRAGMAS = {
    'journal_mode': 'WAL',  # Write-Ahead Logging for concurrency
    'synchronous': 'NORMAL',  # Balance between safety and performance
    'cache_size': -64000,  # 64MB cache size
    'foreign_keys': 'ON',  # Enable foreign key constraints
    'temp_store': 'MEMORY',  # Store temporary data in memory
}
```

## Database Design

### Schema Architecture

#### Advanced Schema Features

**SQLAlchemy 2.0 Model Definitions**
```python
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, Mapped, mapped_column
from datetime import datetime
from typing import List

Base = declarative_base()

class TagsTable(Base):
    __tablename__ = 'tags'
    
    tag_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_tag: Mapped[str] = mapped_column(String, nullable=False)
    tag: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)
    
    # Type-safe relationships
    translations: Mapped[List["TagTranslationsTable"]] = relationship(back_populates="tag", cascade="all, delete-orphan")
    usage_counts: Mapped[List["TagUsageCountsTable"]] = relationship(back_populates="tag", cascade="all, delete-orphan")
    status_records: Mapped[List["TagStatusTable"]] = relationship(back_populates="tag", cascade="all, delete-orphan")
    
    def __repr__(self) -> str:
        return f"<Tag(id={self.tag_id}, tag='{self.tag}')>"
```

**Complex Relationship Management**
```python
class TagStatusTable(Base):
    __tablename__ = 'tag_status'
    
    tag_id: Mapped[int] = mapped_column(Integer, ForeignKey('tags.tag_id'), primary_key=True)
    format_id: Mapped[int] = mapped_column(Integer, ForeignKey('tag_formats.format_id'), primary_key=True)
    type_id: Mapped[int] = mapped_column(Integer, nullable=False)
    alias: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    preferred_tag_id: Mapped[int] = mapped_column(Integer, ForeignKey('tags.tag_id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)
    
    # Relationships with proper typing
    tag: Mapped["TagsTable"] = relationship("TagsTable", foreign_keys=[tag_id], back_populates="status_records")
    preferred_tag: Mapped["TagsTable"] = relationship("TagsTable", foreign_keys=[preferred_tag_id])
    format: Mapped["TagFormatsTable"] = relationship("TagFormatsTable", back_populates="status_records")
```

#### Performance Optimization

**Indexing Strategy**
```sql
-- Primary performance indexes
CREATE INDEX idx_tags_tag ON tags(tag);
CREATE INDEX idx_tags_source_tag ON tags(source_tag);
CREATE INDEX idx_tag_translations_language ON tag_translations(language);
CREATE INDEX idx_tag_usage_counts_format_count ON tag_usage_counts(format_id, count DESC);
CREATE INDEX idx_tag_status_alias ON tag_status(alias);

-- Composite indexes for complex queries
CREATE INDEX idx_tag_status_format_type ON tag_status(format_id, type_id);
CREATE INDEX idx_tag_usage_format_tag ON tag_usage_counts(format_id, tag_id);

-- Full-text search index
CREATE VIRTUAL TABLE tags_fts USING fts5(tag, source_tag, content='tags', content_rowid='tag_id');
```

**Query Optimization Patterns**
```python
from sqlalchemy.orm import selectinload, joinedload
from sqlalchemy import select, func

class OptimizedTagRepository:
    def __init__(self, session: Session):
        self.session = session
    
    def get_tags_with_translations(self, limit: int = 100) -> List[TagsTable]:
        """Optimized query with eager loading to avoid N+1 problems."""
        stmt = (
            select(TagsTable)
            .options(selectinload(TagsTable.translations))
            .limit(limit)
        )
        return self.session.execute(stmt).scalars().all()
    
    def search_tags_with_usage(self, query: str) -> List[TagsTable]:
        """Complex query with joins and aggregations."""
        stmt = (
            select(TagsTable)
            .join(TagUsageCountsTable)
            .where(TagsTable.tag.contains(query))
            .group_by(TagsTable.tag_id)
            .order_by(func.sum(TagUsageCountsTable.count).desc())
        )
        return self.session.execute(stmt).scalars().all()
```

### Migration Management

#### Alembic Configuration
```python
# alembic/env.py
from sqlalchemy import engine_from_config, pool
from alembic import context
from genai_tag_db_tools.data.database_schema import Base

target_metadata = Base.metadata

def run_migrations_online():
    """Run migrations in 'online' mode with database connection."""
    configuration = context.config
    
    # Apply SQLite pragmas for performance
    configuration.set_main_option(
        "sqlalchemy.url", 
        f"sqlite:///{get_database_path()}?check_same_thread=False"
    )
    
    connectable = engine_from_config(
        configuration.get_section(configuration.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Set SQLite pragmas for migration
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()
```

#### Migration Best Practices
```python
"""Add tag popularity scoring

Revision ID: abc123def456
Revises: previous_revision
Create Date: 2024-01-01 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    """Add popularity scoring functionality."""
    # Create new table for popularity scores
    op.create_table(
        'tag_popularity_scores',
        sa.Column('tag_id', sa.Integer(), sa.ForeignKey('tags.tag_id'), primary_key=True),
        sa.Column('format_id', sa.Integer(), sa.ForeignKey('tag_formats.format_id'), primary_key=True),
        sa.Column('popularity_score', sa.Float(), nullable=False, default=0.0),
        sa.Column('calculated_at', sa.DateTime(), nullable=False),
    )
    
    # Add indexes for performance
    op.create_index('idx_popularity_score', 'tag_popularity_scores', ['popularity_score'])
    
    # Populate initial data
    op.execute("""
        INSERT INTO tag_popularity_scores (tag_id, format_id, popularity_score, calculated_at)
        SELECT tc.tag_id, tc.format_id, tc.count * 1.0, datetime('now')
        FROM tag_usage_counts tc
    """)

def downgrade():
    """Remove popularity scoring functionality."""
    op.drop_index('idx_popularity_score', 'tag_popularity_scores')
    op.drop_table('tag_popularity_scores')
```

## Service Architecture

### Repository Pattern Implementation

#### Advanced Repository Pattern
```python
from abc import ABC, abstractmethod
from typing import TypeVar, Generic, List, Optional, Dict, Any
from sqlalchemy.orm import Session

T = TypeVar('T')

class BaseRepository(Generic[T], ABC):
    """Base repository with common CRUD operations."""
    
    def __init__(self, session: Session, model_class: type[T]):
        self.session = session
        self.model_class = model_class
    
    def create(self, entity_data: Dict[str, Any]) -> T:
        """Create new entity with validation."""
        entity = self.model_class(**entity_data)
        self.session.add(entity)
        self.session.flush()  # Get ID without committing
        return entity
    
    def get_by_id(self, entity_id: int) -> Optional[T]:
        """Get entity by primary key."""
        return self.session.get(self.model_class, entity_id)
    
    def update(self, entity: T, update_data: Dict[str, Any]) -> T:
        """Update entity with new data."""
        for key, value in update_data.items():
            if hasattr(entity, key):
                setattr(entity, key, value)
        self.session.flush()
        return entity
    
    def delete(self, entity: T) -> None:
        """Delete entity from database."""
        self.session.delete(entity)
        self.session.flush()

class TagRepository(BaseRepository[TagsTable]):
    """Specialized repository for tag operations."""
    
    def __init__(self, session: Session):
        super().__init__(session, TagsTable)
    
    def find_by_name(self, tag_name: str) -> Optional[TagsTable]:
        """Find tag by exact name match."""
        return self.session.query(TagsTable).filter(
            TagsTable.tag == tag_name
        ).first()
    
    def search_fuzzy(self, query: str, limit: int = 100) -> List[TagsTable]:
        """Search tags with fuzzy matching and ranking."""
        # Use FTS5 for full-text search if available
        return self.session.query(TagsTable).filter(
            TagsTable.tag.contains(query)
        ).order_by(
            func.length(TagsTable.tag),  # Prefer shorter matches
            TagsTable.tag
        ).limit(limit).all()
```

### Service Layer Implementation

#### Business Logic Services
```python
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime

@dataclass
class TagCreationRequest:
    """Request object for tag creation."""
    tag_name: str
    source_tag: str
    translations: Dict[str, str] = None
    format_id: Optional[int] = None

@dataclass
class TagSearchRequest:
    """Request object for tag search."""
    query: str
    language: Optional[str] = None
    format_id: Optional[int] = None
    include_aliases: bool = True
    limit: int = 100

class TagManagementService:
    """High-level service for tag management operations."""
    
    def __init__(self, session: Session):
        self.session = session
        self.tag_repository = TagRepository(session)
        self.translation_repository = TagTranslationRepository(session)
    
    def create_tag(self, request: TagCreationRequest) -> TagsTable:
        """Create new tag with comprehensive validation."""
        try:
            # Validate input
            self._validate_tag_creation(request)
            
            # Check for duplicates
            existing_tag = self.tag_repository.find_by_name(request.tag_name)
            if existing_tag:
                raise TagAlreadyExistsError(f"Tag '{request.tag_name}' already exists")
            
            # Create tag
            tag_data = {
                'tag': request.tag_name.strip().lower(),
                'source_tag': request.source_tag.strip(),
                'created_at': datetime.now(),
                'updated_at': datetime.now(),
            }
            
            tag = self.tag_repository.create(tag_data)
            
            # Add translations if provided
            if request.translations:
                self._add_translations(tag, request.translations)
            
            # Create default status record
            if request.format_id:
                self._create_default_status(tag, request.format_id)
            
            self.session.commit()
            return tag
            
        except Exception as e:
            self.session.rollback()
            raise TagManagementError(f"Failed to create tag: {e}") from e
    
    def search_tags(self, request: TagSearchRequest) -> List[TagsTable]:
        """Search tags with advanced filtering and ranking."""
        # Implement complex search logic with multiple criteria
        base_query = self.tag_repository.search_fuzzy(request.query, request.limit)
        
        # Apply additional filters
        if request.language:
            # Filter by translation language
            pass
        
        if request.format_id:
            # Filter by format
            pass
        
        return base_query
```

### Performance Optimization

#### Bulk Operations
```python
import polars as pl
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterator, Tuple

class BulkTagImportService:
    """Service for efficient bulk tag operations."""
    
    def __init__(self, session: Session):
        self.session = session
        self.batch_size = 1000
        self.max_workers = 4
    
    def import_from_csv(self, csv_path: str) -> Dict[str, int]:
        """Import tags from CSV with optimized bulk processing."""
        try:
            # Load data with Polars for performance
            df = pl.read_csv(csv_path)
            
            # Validate data structure
            self._validate_csv_structure(df)
            
            # Convert to batches for processing
            batches = self._create_batches(df.to_dicts())
            
            # Process batches in parallel
            results = self._process_batches_parallel(batches)
            
            # Aggregate results
            total_inserted = sum(r['inserted'] for r in results)
            total_skipped = sum(r['skipped'] for r in results)
            total_errors = sum(r['errors'] for r in results)
            
            self.session.commit()
            
            return {
                'inserted': total_inserted,
                'skipped': total_skipped,
                'errors': total_errors,
                'total': len(df)
            }
            
        except Exception as e:
            self.session.rollback()
            raise BulkImportError(f"Bulk import failed: {e}") from e
    
    def _process_batches_parallel(self, batches: List[List[Dict]]) -> List[Dict[str, int]]:
        """Process batches in parallel for improved performance."""
        results = []
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_batch = {
                executor.submit(self._process_batch, batch): batch 
                for batch in batches
            }
            
            for future in as_completed(future_to_batch):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    # Log error and continue with other batches
                    results.append({'inserted': 0, 'skipped': 0, 'errors': 1})
        
        return results
```

## GUI Architecture

### Modern Qt Development

#### Advanced Widget Implementation
```python
from PySide6.QtWidgets import QWidget, QVBoxLayout, QProgressBar
from PySide6.QtCore import Signal, QThread, QTimer, Slot
from PySide6.QtGui import QStandardItemModel, QStandardItem
from typing import Optional, List

class AdvancedTagSearchWidget(QWidget):
    """Advanced tag search widget with real-time updates."""
    
    # Type-safe signals
    tag_selected = Signal(str)
    search_completed = Signal(list)
    error_occurred = Signal(str)
    
    def __init__(self, search_service: TagSearchService, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.search_service = search_service
        self.search_timer = QTimer()
        self.current_search_thread: Optional[TagSearchThread] = None
        
        self._setup_ui()
        self._setup_connections()
        self._setup_search_timer()
    
    def _setup_ui(self):
        """Setup user interface with modern Qt features."""
        layout = QVBoxLayout(self)
        
        # Search input with advanced features
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search tags...")
        self.search_input.setClearButtonEnabled(True)
        layout.addWidget(self.search_input)
        
        # Progress indicator
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # Results view with model/view architecture
        self.results_view = QTableView()
        self.results_model = TagSearchResultModel()
        self.results_view.setModel(self.results_model)
        layout.addWidget(self.results_view)
    
    def _setup_connections(self):
        """Setup signal/slot connections."""
        self.search_input.textChanged.connect(self._on_search_text_changed)
        self.search_timer.timeout.connect(self._perform_search)
        self.results_view.doubleClicked.connect(self._on_result_selected)
    
    def _setup_search_timer(self):
        """Setup debounced search timer."""
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(300)  # 300ms debounce
    
    @Slot(str)
    def _on_search_text_changed(self, text: str):
        """Handle search text changes with debouncing."""
        if self.current_search_thread and self.current_search_thread.isRunning():
            self.current_search_thread.requestInterruption()
        
        self.search_timer.stop()
        if text.strip():
            self.search_timer.start()
    
    @Slot()
    def _perform_search(self):
        """Perform search in background thread."""
        query = self.search_input.text().strip()
        if not query:
            return
        
        # Show progress
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate progress
        
        # Start search thread
        self.current_search_thread = TagSearchThread(self.search_service, query)
        self.current_search_thread.search_completed.connect(self._on_search_completed)
        self.current_search_thread.error_occurred.connect(self._on_search_error)
        self.current_search_thread.start()
    
    @Slot(list)
    def _on_search_completed(self, results: List[TagsTable]):
        """Handle search completion."""
        self.progress_bar.setVisible(False)
        self.results_model.set_results(results)
        self.search_completed.emit(results)
    
    @Slot(str)
    def _on_search_error(self, error_message: str):
        """Handle search errors."""
        self.progress_bar.setVisible(False)
        self.error_occurred.emit(error_message)

class TagSearchThread(QThread):
    """Background thread for tag search operations."""
    
    search_completed = Signal(list)
    error_occurred = Signal(str)
    
    def __init__(self, search_service: TagSearchService, query: str):
        super().__init__()
        self.search_service = search_service
        self.query = query
    
    def run(self):
        """Execute search in background thread."""
        try:
            results = self.search_service.search_tags(self.query)
            if not self.isInterruptionRequested():
                self.search_completed.emit(results)
        except Exception as e:
            if not self.isInterruptionRequested():
                self.error_occurred.emit(str(e))
```

#### Model/View Architecture
```python
from PySide6.QtCore import QAbstractTableModel, Qt, QModelIndex
from PySide6.QtGui import QFont, QColor
from typing import List, Any, Optional

class TagSearchResultModel(QAbstractTableModel):
    """Model for displaying tag search results."""
    
    COLUMNS = ['Tag', 'Source', 'Translations', 'Usage Count']
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._results: List[TagsTable] = []
    
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._results)
    
    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self.COLUMNS)
    
    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or index.row() >= len(self._results):
            return None
        
        tag = self._results[index.row()]
        column = index.column()
        
        if role == Qt.DisplayRole:
            if column == 0:
                return tag.tag
            elif column == 1:
                return tag.source_tag
            elif column == 2:
                return ', '.join(t.translation for t in tag.translations[:3])
            elif column == 3:
                return sum(uc.count for uc in tag.usage_counts)
        
        elif role == Qt.FontRole:
            if column == 0:  # Make tag names bold
                font = QFont()
                font.setBold(True)
                return font
        
        elif role == Qt.ForegroundRole:
            if column == 3:  # Color usage count based on value
                usage_count = sum(uc.count for uc in tag.usage_counts)
                if usage_count > 1000:
                    return QColor(Qt.green)
                elif usage_count > 100:
                    return QColor(Qt.blue)
                else:
                    return QColor(Qt.gray)
        
        return None
    
    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.COLUMNS[section]
        return None
    
    def set_results(self, results: List[TagsTable]):
        """Update model with new search results."""
        self.beginResetModel()
        self._results = results
        self.endResetModel()
```

## Testing Architecture

### Comprehensive Testing Strategy

#### Advanced Test Configuration
```python
# conftest.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from genai_tag_db_tools.data.database_schema import Base
from genai_tag_db_tools.services.tag_management import TagManagementService

@pytest.fixture(scope="function")
def test_database():
    """Create isolated test database for each test."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    try:
        yield session
    finally:
        session.close()

@pytest.fixture
def tag_service(test_database):
    """Create tag management service with test database."""
    return TagManagementService(test_database)

@pytest.fixture
def sample_tags(test_database):
    """Create sample tags for testing."""
    service = TagManagementService(test_database)
    
    tags = []
    for i in range(10):
        tag = service.create_tag(TagCreationRequest(
            tag_name=f"test_tag_{i}",
            source_tag=f"source_{i}",
            translations={'ja': f"テスト_{i}"}
        ))
        tags.append(tag)
    
    return tags
```

#### Performance Testing
```python
import pytest
import time
from typing import List

class TestPerformance:
    """Performance tests for critical operations."""
    
    @pytest.mark.slow
    def test_bulk_import_performance(self, tag_service):
        """Test bulk import performance with large dataset."""
        # Create test data
        test_data = [
            {'tag': f'performance_tag_{i}', 'source_tag': f'source_{i}'}
            for i in range(10000)
        ]
        
        start_time = time.time()
        result = tag_service.bulk_import(test_data)
        end_time = time.time()
        
        # Performance assertions
        assert end_time - start_time < 30.0  # Should complete in under 30 seconds
        assert result['inserted'] == 10000
        assert result['errors'] == 0
    
    @pytest.mark.slow
    def test_search_performance(self, tag_service, sample_tags):
        """Test search performance with various query patterns."""
        queries = ['test', 'tag', 'source', 'テスト']
        
        for query in queries:
            start_time = time.time()
            results = tag_service.search_tags(TagSearchRequest(query=query))
            end_time = time.time()
            
            # Performance assertions
            assert end_time - start_time < 1.0  # Should complete in under 1 second
            assert isinstance(results, list)
```

#### GUI Testing
```python
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
from genai_tag_db_tools.gui.widgets.tag_search import TagSearchWidget

@pytest.fixture(scope="session")
def qapp():
    """Create QApplication instance for GUI tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app

class TestTagSearchWidget:
    """GUI tests for tag search widget."""
    
    def test_widget_initialization(self, qapp, tag_service):
        """Test widget initializes correctly."""
        widget = TagSearchWidget(tag_service)
        assert widget.isEnabled()
        assert widget.search_input.placeholderText() == "Search tags..."
    
    def test_search_functionality(self, qapp, tag_service, sample_tags):
        """Test search functionality through GUI."""
        widget = TagSearchWidget(tag_service)
        widget.show()
        
        # Simulate user input
        QTest.keyClicks(widget.search_input, "test")
        
        # Wait for search to complete
        QTest.qWait(500)
        
        # Verify results
        assert widget.results_model.rowCount() > 0
    
    def test_selection_signals(self, qapp, tag_service, sample_tags):
        """Test signal emission on tag selection."""
        widget = TagSearchWidget(tag_service)
        
        selected_tags = []
        widget.tag_selected.connect(lambda tag: selected_tags.append(tag))
        
        # Simulate search and selection
        QTest.keyClicks(widget.search_input, "test")
        QTest.qWait(500)
        
        # Simulate double-click on first result
        index = widget.results_model.index(0, 0)
        widget.results_view.doubleClicked.emit(index)
        
        assert len(selected_tags) == 1
```

## Deployment and Distribution

### Application Packaging

#### PyPI Distribution
```toml
# pyproject.toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/genai_tag_db_tools"]

[tool.hatch.build.targets.wheel.package-data]
genai_tag_db_tools = ["data/*.db"]

[tool.hatch.build.targets.sdist]
exclude = [
    "/.git",
    "/docs",
    "/tests",
    "*.pyc",
]
```

#### Cross-Platform Executable
```python
# build_executable.py
import PyInstaller.__main__
import sys
from pathlib import Path

def build_executable():
    """Build cross-platform executable with PyInstaller."""
    args = [
        '--name=genai-tag-db-tools',
        '--onefile',
        '--windowed',  # No console window on Windows
        '--add-data=src/genai_tag_db_tools/data/*.db;data',
        '--hidden-import=PySide6.QtCore',
        '--hidden-import=PySide6.QtWidgets',
        '--hidden-import=PySide6.QtGui',
        'src/genai_tag_db_tools/main.py'
    ]
    
    PyInstaller.__main__.run(args)

if __name__ == '__main__':
    build_executable()
```

### Performance Monitoring

#### Runtime Performance Monitoring
```python
import functools
import time
import psutil
from typing import Callable, Any

def monitor_performance(func: Callable) -> Callable:
    """Decorator for monitoring function performance."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        # Monitor memory before execution
        process = psutil.Process()
        memory_before = process.memory_info().rss / 1024 / 1024  # MB
        
        # Time execution
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        
        # Monitor memory after execution
        memory_after = process.memory_info().rss / 1024 / 1024  # MB
        
        # Log performance metrics
        execution_time = end_time - start_time
        memory_delta = memory_after - memory_before
        
        if execution_time > 1.0 or memory_delta > 10.0:  # Log slow or memory-intensive operations
            print(f"Performance warning - {func.__name__}: "
                  f"{execution_time:.2f}s, {memory_delta:.1f}MB")
        
        return result
    return wrapper

# Usage in service methods
class TagManagementService:
    @monitor_performance
    def create_tag(self, request: TagCreationRequest) -> TagsTable:
        # Implementation here
        pass
```

This technical specification provides comprehensive guidance for developing, maintaining, and deploying the genai-tag-db-tools application with focus on performance, reliability, and maintainability.