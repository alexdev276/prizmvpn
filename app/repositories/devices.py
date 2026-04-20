from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import utcnow
from app.models import Device


class DeviceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, device_id: int) -> Device | None:
        return await self.session.get(Device, device_id)

    async def get_for_user(self, user_id: int, device_id: int) -> Device | None:
        result = await self.session.execute(
            select(Device).where(
                Device.id == device_id,
                Device.user_id == user_id,
                Device.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_public_id_and_config(self, public_id: str, config_uuid: str) -> Device | None:
        result = await self.session.execute(
            select(Device).where(
                Device.public_id == public_id,
                Device.config_uuid == config_uuid,
                Device.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def public_id_exists(self, public_id: str) -> bool:
        result = await self.session.execute(select(Device.id).where(Device.public_id == public_id))
        return result.scalar_one_or_none() is not None

    async def list_active_for_user(self, user_id: int) -> list[Device]:
        result = await self.session.execute(
            select(Device)
            .where(Device.user_id == user_id, Device.deleted_at.is_(None))
            .order_by(Device.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_billable(self, user_id: int) -> list[Device]:
        result = await self.session.execute(
            select(Device).where(Device.user_id == user_id, Device.deleted_at.is_(None)).order_by(Device.id.asc())
        )
        return list(result.scalars().all())

    async def create(
        self,
        *,
        user_id: int,
        public_id: str,
        title: str,
        config_uuid: str,
        locked_until,
        remnawave_uuid: str | None = None,
        remnawave_username: str | None = None,
        remnawave_subscription_url: str | None = None,
        remnawave_raw: dict | None = None,
        traffic_limit_bytes: int = 0,
    ) -> Device:
        now = utcnow()
        device = Device(
            user_id=user_id,
            public_id=public_id,
            title=title,
            config_uuid=config_uuid,
            remnawave_uuid=remnawave_uuid,
            remnawave_username=remnawave_username,
            remnawave_subscription_url=remnawave_subscription_url,
            remnawave_raw=remnawave_raw,
            traffic_limit_bytes=traffic_limit_bytes,
            locked_until=locked_until,
            last_billed_at=now,
        )
        self.session.add(device)
        await self.session.flush()
        return device

    async def update_config(self, device: Device, config_uuid: str) -> Device:
        device.config_uuid = config_uuid
        await self.session.flush()
        return device

    async def attach_remnawave_user(
        self,
        device: Device,
        *,
        remnawave_uuid: str,
        remnawave_username: str,
        remnawave_subscription_url: str | None,
        remnawave_raw: dict | None,
        traffic_limit_bytes: int,
    ) -> Device:
        device.remnawave_uuid = remnawave_uuid
        device.remnawave_username = remnawave_username
        device.remnawave_subscription_url = remnawave_subscription_url
        device.remnawave_raw = remnawave_raw
        device.traffic_used = 0
        device.traffic_limit_bytes = traffic_limit_bytes
        await self.session.flush()
        return device

    async def set_traffic_used(self, device: Device, traffic_used: int) -> Device:
        device.traffic_used = traffic_used
        await self.session.flush()
        return device

    async def set_traffic_limit(self, device: Device, traffic_limit_bytes: int) -> Device:
        device.traffic_limit_bytes = traffic_limit_bytes
        await self.session.flush()
        return device

    async def set_billed_at(self, device: Device, billed_at) -> Device:
        device.last_billed_at = billed_at
        await self.session.flush()
        return device

    async def soft_delete(self, device: Device) -> Device:
        device.deleted_at = utcnow()
        await self.session.flush()
        return device
