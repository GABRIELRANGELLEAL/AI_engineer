#!/usr/bin/env python
"""Test script to verify database schema and basic operations."""

import os
from datetime import datetime, date, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import numpy as np

from models import (
    Base, User, Case, Filing, Analysis, Task, Draft, ExampleBank,
    FilingStatusEnum, DeadlineTypeEnum, ExampleTypeEnum
)

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def test_database():
    """Test all database operations."""
    session = SessionLocal()

    try:
        print("Testing User creation...")
        user = User(
            name="John Doe",
            email="john@example.com",
            google_calendar_token={"access_token": "dummy_token"}
        )
        session.add(user)
        session.commit()
        print(f"✓ User created: {user.name} (ID: {user.id})")

        print("\nTesting Case creation...")
        case = Case(
            case_number="0001234-56.2026.8.26.0100",
            court="TJ-SP",
            lawyer_id=user.id,
            active=True
        )
        session.add(case)
        session.commit()
        print(f"✓ Case created: {case.case_number} (ID: {case.id})")

        print("\nTesting Filing creation...")
        filing = Filing(
            case_id=case.id,
            raw_content="This is a sample filing content with important legal information.",
            filing_date=datetime.utcnow(),
            status=FilingStatusEnum.NEW
        )
        session.add(filing)
        session.commit()
        print(f"✓ Filing created (ID: {filing.id}, Status: {filing.status})")

        print("\nTesting Analysis creation...")
        analysis = Analysis(
            filing_id=filing.id,
            action_required=True,
            justification="The filing requires immediate action due to the deadline.",
            rag_examples_used=[{"id": 1, "similarity": 0.92}],
            lawyer_confirmed=False
        )
        session.add(analysis)
        session.commit()
        print(f"✓ Analysis created (ID: {analysis.id}, Action Required: {analysis.action_required})")

        print("\nTesting Task creation...")
        task = Task(
            analysis_id=analysis.id,
            description="Review and prepare response to the court filing",
            deadline_type=DeadlineTypeEnum.REQUEST,
            due_date=date.today() + timedelta(days=5),
            lawyer_confirmed=False
        )
        session.add(task)
        session.commit()
        print(f"✓ Task created (ID: {task.id}, Deadline Type: {task.deadline_type})")

        print("\nTesting Draft creation...")
        draft = Draft(
            task_id=task.id,
            content="This is the first draft of the response document.",
            version=1,
            chosen=False,
            edited_by_lawyer=False
        )
        session.add(draft)
        session.commit()
        print(f"✓ Draft created (ID: {draft.id}, Version: {draft.version})")

        print("\nTesting ExampleBank with embeddings...")
        embedding = np.random.randn(1536).tolist()
        example = ExampleBank(
            type=ExampleTypeEnum.ANALYSIS,
            content="Example analysis from past case showing similar legal issue.",
            embedding=embedding,
            metadata={"case_number": "0000123-45.2025.8.26.0100", "court": "TJ-SP"},
            source_draft_id=None
        )
        session.add(example)
        session.commit()
        print(f"✓ ExampleBank created (ID: {example.id}, Type: {example.type})")

        print("\n" + "="*60)
        print("Testing data retrieval...")
        print("="*60)

        retrieved_user = session.query(User).filter_by(id=user.id).first()
        print(f"\n✓ Retrieved User: {retrieved_user.name} ({retrieved_user.email})")

        retrieved_case = session.query(Case).filter_by(id=case.id).first()
        print(f"✓ Retrieved Case: {retrieved_case.case_number}")
        print(f"  - Lawyer: {retrieved_case.lawyer.name}")
        print(f"  - Active: {retrieved_case.active}")

        retrieved_filing = session.query(Filing).filter_by(id=filing.id).first()
        print(f"✓ Retrieved Filing: {retrieved_filing.status}")
        print(f"  - Case: {retrieved_filing.case.case_number}")
        print(f"  - Content length: {len(retrieved_filing.raw_content)} chars")

        retrieved_analysis = session.query(Analysis).filter_by(id=analysis.id).first()
        print(f"✓ Retrieved Analysis:")
        print(f"  - Action Required: {retrieved_analysis.action_required}")
        print(f"  - Justification: {retrieved_analysis.justification}")
        print(f"  - RAG Examples: {retrieved_analysis.rag_examples_used}")

        retrieved_task = session.query(Task).filter_by(id=task.id).first()
        print(f"✓ Retrieved Task:")
        print(f"  - Description: {retrieved_task.description}")
        print(f"  - Deadline Type: {retrieved_task.deadline_type}")
        print(f"  - Due Date: {retrieved_task.due_date}")

        retrieved_draft = session.query(Draft).filter_by(id=draft.id).first()
        print(f"✓ Retrieved Draft:")
        print(f"  - Version: {retrieved_draft.version}")
        print(f"  - Content length: {len(retrieved_draft.content)} chars")

        retrieved_example = session.query(ExampleBank).filter_by(id=example.id).first()
        print(f"✓ Retrieved ExampleBank:")
        print(f"  - Type: {retrieved_example.type}")
        print(f"  - Embedding dimension: {len(retrieved_example.embedding)}")
        print(f"  - Metadata: {retrieved_example.metadata}")

        print("\n" + "="*60)
        print("✓ ALL TESTS PASSED!")
        print("="*60)

        print("\nDatabase statistics:")
        print(f"  - Users: {session.query(User).count()}")
        print(f"  - Cases: {session.query(Case).count()}")
        print(f"  - Filings: {session.query(Filing).count()}")
        print(f"  - Analyses: {session.query(Analysis).count()}")
        print(f"  - Tasks: {session.query(Task).count()}")
        print(f"  - Drafts: {session.query(Draft).count()}")
        print(f"  - Examples: {session.query(ExampleBank).count()}")

    except Exception as e:
        print(f"\n✗ Error: {str(e)}")
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == '__main__':
    test_database()
