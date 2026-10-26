"""
scripts/seed_tenants.py — Seed initial demo tenants

Creates 'demo-company' if it does not already exist.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select
from app.database import get_session_factory
from app.models.tenant import Tenant

TENANTS = [
    {
        "name": "Demo Company",
        "slug": "demo-company",
        "description": "Enterprise SaaS Solutions Provider",
        "config": {
            "assistant_name": "Demo Assistant",
            "company_name": "Demo Company",
            "welcome_message": "Hello! I am your Demo Company assistant. How can I help you today?",
            "brand_color": "#7c3aed",
            "suggested_questions": [
                "What plans do you offer?",
                "How do I get started with a free trial?",
                "How do I contact support?",
                "What integrations do you support?",
            ],
        },
    },
]


async def seed():
    session_factory = get_session_factory()
    async with session_factory() as session:
        for t_data in TENANTS:
            result = await session.execute(
                select(Tenant).where(Tenant.slug == t_data["slug"])
            )
            existing = result.scalar_one_or_none()
            if existing:
                print(f"Tenant '{t_data['slug']}' already exists.")
            else:
                tenant = Tenant(
                    name=t_data["name"],
                    slug=t_data["slug"],
                    description=t_data["description"],
                    config=t_data["config"],
                    is_active=True,
                )
                session.add(tenant)
                print(f"Created tenant '{t_data['slug']}'.")
        await session.commit()
        print("[OK] All demo tenants seeded successfully.")


if __name__ == "__main__":
    asyncio.run(seed())
