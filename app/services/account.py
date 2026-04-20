from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import quote

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import as_utc, utcnow
from app.models import Device, User
from app.repositories.devices import DeviceRepository
from app.repositories.transactions import TransactionRepository
from app.repositories.users import UserRepository
from app.services.money import DEVICE_HOURLY_PRICE_MICRORUB, DEVICE_MONTHLY_PRICE_RUB


class AccountError(ValueError):
    pass


@dataclass(frozen=True)
class DeviceView:
    device: Device
    can_delete: bool
    config_link: str


class AccountService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)
        self.devices = DeviceRepository(session)
        self.transactions = TransactionRepository(session)

    async def bill_user_devices(self, user: User) -> int:
        now = utcnow()
        total_charged = 0
        for device in await self.devices.list_billable(user.id):
            last_billed_at = as_utc(device.last_billed_at)
            elapsed_hours = int((now - last_billed_at).total_seconds() // 3600)
            if elapsed_hours <= 0:
                continue

            charge = elapsed_hours * DEVICE_HOURLY_PRICE_MICRORUB
            await self.users.change_balance(user, -charge)
            await self.transactions.create(
                user_id=user.id,
                device_id=device.id,
                kind="device_charge",
                amount_microrub=-charge,
                balance_after_microrub=user.balance_microrub,
                description=f"Списание оплаты за устройство {device.public_id}",
            )
            await self.devices.set_billed_at(device, last_billed_at + timedelta(hours=elapsed_hours))
            total_charged += charge

        if total_charged:
            await self.session.commit()
        return total_charged

    async def list_device_views(self, user: User) -> list[DeviceView]:
        now = utcnow()
        devices = await self.devices.list_active_for_user(user.id)
        return [
            DeviceView(
                device=device,
                can_delete=as_utc(device.locked_until) <= now,
                config_link=self.config_link(device),
            )
            for device in devices
        ]

    async def add_device(self, user: User, *, title: str) -> Device:
        title = title.strip() or "IPhone 16"
        if len(title) > 120:
            raise AccountError("Название устройства слишком длинное.")
        public_id = await self._generate_public_id()
        device = await self.devices.create(
            user_id=user.id,
            public_id=public_id,
            title=title,
            config_uuid=str(uuid.uuid4()),
            locked_until=utcnow() + timedelta(hours=24),
        )
        await self.transactions.create(
            user_id=user.id,
            device_id=device.id,
            kind="device_added",
            amount_microrub=0,
            balance_after_microrub=user.balance_microrub,
            description=f"Добавлено устройство {device.public_id}",
        )
        await self.session.commit()
        return device

    async def delete_device(self, user: User, device_id: int) -> None:
        device = await self.devices.get_for_user(user.id, device_id)
        if not device:
            raise AccountError("Устройство не найдено.")
        if as_utc(device.locked_until) > utcnow():
            raise AccountError("Это устройство можно удалить только через 24 часа после добавления.")
        await self.devices.soft_delete(device)
        await self.transactions.create(
            user_id=user.id,
            device_id=device.id,
            kind="device_deleted",
            amount_microrub=0,
            balance_after_microrub=user.balance_microrub,
            description=f"Удалено устройство {device.public_id}",
        )
        await self.session.commit()

    async def replace_device_config(self, user: User, device_id: int) -> Device:
        device = await self.devices.get_for_user(user.id, device_id)
        if not device:
            raise AccountError("Устройство не найдено.")
        await self.devices.update_config(device, str(uuid.uuid4()))
        await self.transactions.create(
            user_id=user.id,
            device_id=device.id,
            kind="device_replaced",
            amount_microrub=0,
            balance_after_microrub=user.balance_microrub,
            description=f"Обновлены настройки устройства {device.public_id}",
        )
        await self.session.commit()
        return device

    async def get_public_device(self, public_id: str, config_uuid: str) -> Device | None:
        return await self.devices.get_by_public_id_and_config(public_id, config_uuid)

    def config_link(self, device: Device) -> str:
        return f"{self.settings.BASE_URL.rstrip('/')}/subscription/{device.public_id}/{device.config_uuid}.txt"

    def render_vless_config(self, device: Device) -> str:
        tag = quote(f"{device.title}-{device.public_id}")
        return f"vless://{device.config_uuid}@example.com:443?type=tcp&security=tls#{tag}"

    async def _generate_public_id(self) -> str:
        for _ in range(20):
            public_id = "".join(str(secrets.randbelow(10)) for _ in range(10))
            if not await self.devices.public_id_exists(public_id):
                return public_id
        raise AccountError("Не удалось создать ID устройства. Попробуйте еще раз.")


def device_monthly_price_label() -> str:
    return f"{int(DEVICE_MONTHLY_PRICE_RUB)}Р"

