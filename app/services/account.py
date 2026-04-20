from __future__ import annotations

import logging
import secrets
import re
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import as_utc, utcnow
from app.models import Device, User
from app.repositories.devices import DeviceRepository
from app.repositories.transactions import TransactionRepository
from app.repositories.users import UserRepository
from app.services.money import DEVICE_HOURLY_PRICE_MICRORUB, DEVICE_MONTHLY_PRICE_RUB
from app.services.remnawave import RemnawaveClient, RemnawaveError


logger = logging.getLogger(__name__)


class AccountError(ValueError):
    pass


@dataclass(frozen=True)
class DeviceView:
    device: Device
    can_delete: bool
    config_link: str


class AccountService:
    def __init__(self, session: AsyncSession, settings: Settings, remnawave_client: RemnawaveClient) -> None:
        self.session = session
        self.settings = settings
        self.remnawave_client = remnawave_client
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

    async def refresh_device_usage(self, user: User) -> None:
        total_used = 0
        total_limit = 0
        changed = False
        for device in await self.devices.list_active_for_user(user.id):
            if device.remnawave_uuid:
                try:
                    usage = await self.remnawave_client.get_user_usage(device.remnawave_uuid)
                    traffic_used = int(usage.get("trafficUsedBytes") or usage.get("usedTrafficBytes") or device.traffic_used)
                    if traffic_used != device.traffic_used:
                        await self.devices.set_traffic_used(device, traffic_used)
                        changed = True
                except (RemnawaveError, ValueError):
                    pass
            total_used += device.traffic_used
            total_limit += device.traffic_limit_bytes

        if user.traffic_used != total_used:
            await self.users.set_traffic_used(user, total_used)
            changed = True
        if user.traffic_limit_bytes != total_limit:
            user.traffic_limit_bytes = total_limit
            user.updated_at = utcnow()
            changed = True
        if changed:
            await self.session.commit()

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
        remna_user = await self._create_remnawave_device_user(user, public_id)
        device = await self.devices.create(
            user_id=user.id,
            public_id=public_id,
            title=title,
            config_uuid=str(uuid.uuid4()),
            locked_until=utcnow() + timedelta(hours=24),
            remnawave_uuid=remna_user.uuid,
            remnawave_username=remna_user.username,
            remnawave_subscription_url=remna_user.subscription_url,
            remnawave_raw=remna_user.raw,
            traffic_limit_bytes=self.settings.REMNA_TRAFFIC_LIMIT_BYTES,
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
        if device.remnawave_uuid:
            try:
                await self.remnawave_client.disable_user(device.remnawave_uuid)
            except RemnawaveError:
                pass
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
        old_remnawave_uuid = device.remnawave_uuid
        remna_user = await self._create_remnawave_device_user(user, device.public_id)
        if old_remnawave_uuid:
            try:
                await self.remnawave_client.disable_user(old_remnawave_uuid)
            except RemnawaveError:
                pass
        await self.devices.update_config(device, str(uuid.uuid4()))
        await self.devices.attach_remnawave_user(
            device,
            remnawave_uuid=remna_user.uuid,
            remnawave_username=remna_user.username,
            remnawave_subscription_url=remna_user.subscription_url,
            remnawave_raw=remna_user.raw,
            traffic_limit_bytes=self.settings.REMNA_TRAFFIC_LIMIT_BYTES,
        )
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

    async def render_device_config(self, device: Device) -> str:
        if device.remnawave_subscription_url:
            return await self.remnawave_client.get_subscription(device.remnawave_subscription_url)
        if device.remnawave_uuid:
            username = device.remnawave_username or f"{device.title}-{device.public_id}"
            return await self.remnawave_client.get_vless_config(remnawave_uuid=device.remnawave_uuid, email=username)
        raise AccountError("Устройство еще не создано в Remnawave.")

    async def _generate_public_id(self) -> str:
        for _ in range(20):
            public_id = "".join(str(secrets.randbelow(10)) for _ in range(10))
            if not await self.devices.public_id_exists(public_id):
                return public_id
        raise AccountError("Не удалось создать ID устройства. Попробуйте еще раз.")

    async def _create_remnawave_device_user(self, user: User, public_id: str):
        username = self._device_username(user, public_id)
        try:
            return await self.remnawave_client.add_user(
                username=username,
                days=self.settings.REMNA_DEFAULT_DAYS,
                traffic_limit_bytes=self.settings.REMNA_TRAFFIC_LIMIT_BYTES,
            )
        except RemnawaveError as exc:
            logger.exception(
                "Failed to create Remnawave device user. app_user_id=%s public_id=%s remnawave_username=%s",
                user.id,
                public_id,
                username,
            )
            raise AccountError("Не удалось создать устройство в Remnawave. Попробуйте позже.") from exc

    @staticmethod
    def _device_username(user: User, public_id: str) -> str:
        email_slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", user.email.lower()).strip("-_")
        max_prefix_length = max(3, 36 - len(public_id) - 1)
        email_slug = email_slug[:max_prefix_length].strip("-_") or "user"
        return f"{email_slug}-{public_id}"[:36]


def device_monthly_price_label() -> str:
    return f"{int(DEVICE_MONTHLY_PRICE_RUB)}Р"
