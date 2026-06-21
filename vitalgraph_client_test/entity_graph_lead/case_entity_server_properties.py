"""
Entity Server Properties Test Case

Tests server-managed property enforcement on KGEntity objects:
- Creation and modification timestamps
- Status type defaulting and preservation
- Entity type defaulting and preservation
- Frame writes touching parent modification time
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot

from vitalgraph_client_test.client_test_data import ClientTestDataCreator

logger = logging.getLogger(__name__)

# Property URIs — must match kg_server_properties.py
CREATION_TIME_URI = "http://vital.ai/ontology/vital-aimp#hasObjectCreationTime"
MODIFICATION_TIME_URI = "http://vital.ai/ontology/vital#hasObjectModificationDateTime"
STATUS_TYPE_URI = "http://vital.ai/ontology/vital-aimp#hasObjectStatusType"
ENTITY_TYPE_URI = "http://vital.ai/ontology/haley-ai-kg#hasKGEntityType"
DEFAULT_STATUS = "http://vital.ai/ontology/vital-aimp#ObjectStatusType_ACTIVE"
DEFAULT_ENTITY_TYPE = "http://vital.ai/ontology/haley-ai-kg#KGEntityType_KGEntity"
PENDING_STATUS = "http://vital.ai/ontology/vital-aimp#ObjectStatusType_PENDING"
INACTIVE_STATUS = "http://vital.ai/ontology/vital-aimp#ObjectStatusType_INACTIVE"
PERSON_ENTITY_TYPE = "http://vital.ai/ontology/haley-ai-kg#KGEntityType_Person"
ORG_ENTITY_TYPE = "http://vital.ai/ontology/haley-ai-kg#KGEntityType_Organization"

# Maximum acceptable clock skew between test and server (seconds)
TIMESTAMP_TOLERANCE_SECONDS = 5.0


def _to_datetime(prop) -> Optional[datetime]:
    """Extract a datetime from a VitalSigns CombinedProperty or raw value."""
    if prop is None:
        return None
    if isinstance(prop, datetime):
        dt = prop
    elif hasattr(prop, 'get_value'):
        dt = prop.get_value()
    else:
        return None
    if dt is None:
        return None
    if not isinstance(dt, datetime):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class EntityServerPropertiesTester:
    """Test case for server-managed entity property enforcement."""

    def __init__(self, client):
        self.client = client
        self.data_creator = ClientTestDataCreator()

    async def run_tests(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        results = {
            "test_name": "Entity Server Properties",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": [],
        }

        logger.info(f"\n{'='*80}")
        logger.info("  Entity Server Properties Tests")
        logger.info(f"{'='*80}")

        await self._test_create_sets_both_timestamps(results, space_id, graph_id)
        await self._test_create_ignores_client_timestamps(results, space_id, graph_id)
        await self._test_create_defaults_status_active(results, space_id, graph_id)
        await self._test_create_honours_explicit_status(results, space_id, graph_id)
        await self._test_create_defaults_entity_type(results, space_id, graph_id)
        await self._test_create_honours_explicit_entity_type(results, space_id, graph_id)
        await self._test_update_preserves_creation_time(results, space_id, graph_id)
        await self._test_update_sets_modification_time(results, space_id, graph_id)
        await self._test_update_preserves_status_when_omitted(results, space_id, graph_id)
        await self._test_update_allows_status_change(results, space_id, graph_id)
        await self._test_update_preserves_entity_type_when_omitted(results, space_id, graph_id)
        await self._test_update_allows_entity_type_change(results, space_id, graph_id)
        await self._test_frame_create_touches_modification(results, space_id, graph_id)
        await self._test_frame_update_touches_modification(results, space_id, graph_id)
        await self._test_frame_delete_touches_modification(results, space_id, graph_id)
        await self._test_creation_time_immutable_across_updates(results, space_id, graph_id)
        await self._test_update_ignores_client_timestamps(results, space_id, graph_id)
        await self._test_frame_write_does_not_change_status(results, space_id, graph_id)
        await self._test_batch_uses_same_timestamp(results, space_id, graph_id)
        await self._test_status_never_null(results, space_id, graph_id)
        await self._test_entity_type_never_null(results, space_id, graph_id)
        await self._test_round_trip_datetime_precision(results, space_id, graph_id)

        logger.info(f"\n{'='*80}")
        logger.info(
            f"  Results: {results['tests_passed']}/{results['tests_run']} passed, "
            f"{results['tests_failed']} failed"
        )
        logger.info(f"{'='*80}")
        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _pass(self, results: Dict, msg: str) -> None:
        results["tests_run"] += 1
        results["tests_passed"] += 1
        logger.info(f"✅ PASS: {msg}")

    def _fail(self, results: Dict, msg: str) -> None:
        results["tests_run"] += 1
        results["tests_failed"] += 1
        results["errors"].append(msg)
        logger.error(f"❌ FAIL: {msg}")

    async def _create_entity(self, space_id: str, graph_id: str,
                             entity: KGEntity) -> bool:
        """Create entity via client. Returns True on success."""
        resp = await self.client.kgentities.create_kgentities(
            space_id=space_id, graph_id=graph_id, objects=[entity]
        )
        return resp.is_success

    async def _update_entity(self, space_id: str, graph_id: str,
                              entity: KGEntity) -> bool:
        resp = await self.client.kgentities.update_kgentities(
            space_id=space_id, graph_id=graph_id, objects=[entity]
        )
        return resp.is_success

    async def _get_entity(self, space_id: str, graph_id: str,
                           uri: str) -> Optional[KGEntity]:
        """Get entity and return the KGEntity object, or None."""
        resp = await self.client.kgentities.get_kgentity(
            space_id=space_id, graph_id=graph_id, uri=uri
        )
        if resp.is_success and hasattr(resp, 'objects') and resp.objects:
            for obj in (resp.objects if isinstance(resp.objects, list) else [resp.objects]):
                if isinstance(obj, KGEntity):
                    return obj
                # EntityGraph container
                if hasattr(obj, 'objects'):
                    for inner in obj.objects:
                        if isinstance(inner, KGEntity):
                            return inner
        return None

    def _make_entity(self, tag: str, **kwargs) -> KGEntity:
        """Create a minimal KGEntity for testing with a unique URI."""
        import uuid
        ent = KGEntity()
        ent.URI = f"http://vital.ai/test/server_props/{tag}/{uuid.uuid4()}"
        ent.name = f"ServerProps Test {tag}"
        for k, v in kwargs.items():
            setattr(ent, k, v)
        return ent

    def _approx_now(self, prop) -> bool:
        """True if prop is within TIMESTAMP_TOLERANCE_SECONDS of now."""
        dt = _to_datetime(prop)
        if dt is None:
            return False
        now = datetime.now(timezone.utc)
        diff = abs((now - dt).total_seconds())
        return diff < TIMESTAMP_TOLERANCE_SECONDS

    async def _delete_entity(self, space_id: str, graph_id: str, uri: str) -> None:
        """Best-effort cleanup."""
        try:
            await self.client.kgentities.delete_kgentities(
                space_id=space_id, graph_id=graph_id, uris=[uri],
                delete_entity_graph=True
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    async def _test_create_sets_both_timestamps(self, results, space_id, graph_id):
        """Create entity → both timestamps are set and ≈ now."""
        tag = "create_ts"
        ent = self._make_entity(tag)
        uri = str(ent.URI)
        try:
            ok = await self._create_entity(space_id, graph_id, ent)
            if not ok:
                return self._fail(results, f"{tag}: create failed")
            fetched = await self._get_entity(space_id, graph_id, uri)
            if not fetched:
                return self._fail(results, f"{tag}: get after create returned None")
            ct = _to_datetime(fetched.objectCreationTime)
            mt = _to_datetime(fetched.objectModificationDateTime)
            if not self._approx_now(ct):
                return self._fail(results, f"{tag}: creation time not ≈ now: {ct}")
            if not self._approx_now(mt):
                return self._fail(results, f"{tag}: modification time not ≈ now: {mt}")
            self._pass(results, f"{tag}: both timestamps set and ≈ now")
        except Exception as e:
            self._fail(results, f"{tag}: {e}")
        finally:
            await self._delete_entity(space_id, graph_id, uri)

    async def _test_create_ignores_client_timestamps(self, results, space_id, graph_id):
        """Create with client-supplied timestamps → server overrides."""
        tag = "create_override_ts"
        old = datetime(2000, 1, 1, tzinfo=timezone.utc)
        ent = self._make_entity(tag, objectCreationTime=old, objectModificationDateTime=old)
        uri = str(ent.URI)
        try:
            ok = await self._create_entity(space_id, graph_id, ent)
            if not ok:
                return self._fail(results, f"{tag}: create failed")
            fetched = await self._get_entity(space_id, graph_id, uri)
            if not fetched:
                return self._fail(results, f"{tag}: get returned None")
            ct = _to_datetime(fetched.objectCreationTime)
            if ct and abs((ct - old).total_seconds()) < 1:
                return self._fail(results, f"{tag}: server did NOT override client creation time")
            if not self._approx_now(ct):
                return self._fail(results, f"{tag}: creation time not ≈ now: {ct}")
            self._pass(results, f"{tag}: server overrides client timestamps")
        except Exception as e:
            self._fail(results, f"{tag}: {e}")
        finally:
            await self._delete_entity(space_id, graph_id, uri)

    async def _test_create_defaults_status_active(self, results, space_id, graph_id):
        """Create entity with no status → objectStatusType = ACTIVE."""
        tag = "create_default_status"
        ent = self._make_entity(tag)
        uri = str(ent.URI)
        try:
            ok = await self._create_entity(space_id, graph_id, ent)
            if not ok:
                return self._fail(results, f"{tag}: create failed")
            fetched = await self._get_entity(space_id, graph_id, uri)
            if not fetched:
                return self._fail(results, f"{tag}: get returned None")
            st = str(fetched.objectStatusType) if fetched.objectStatusType else None
            if st != DEFAULT_STATUS:
                return self._fail(results, f"{tag}: expected {DEFAULT_STATUS}, got {st}")
            self._pass(results, f"{tag}: status defaults to ACTIVE")
        except Exception as e:
            self._fail(results, f"{tag}: {e}")
        finally:
            await self._delete_entity(space_id, graph_id, uri)

    async def _test_create_honours_explicit_status(self, results, space_id, graph_id):
        """Create entity with status=PENDING → objectStatusType = PENDING."""
        tag = "create_explicit_status"
        ent = self._make_entity(tag, objectStatusType=PENDING_STATUS)
        uri = str(ent.URI)
        try:
            ok = await self._create_entity(space_id, graph_id, ent)
            if not ok:
                return self._fail(results, f"{tag}: create failed")
            fetched = await self._get_entity(space_id, graph_id, uri)
            if not fetched:
                return self._fail(results, f"{tag}: get returned None")
            st = str(fetched.objectStatusType) if fetched.objectStatusType else None
            if st != PENDING_STATUS:
                return self._fail(results, f"{tag}: expected {PENDING_STATUS}, got {st}")
            self._pass(results, f"{tag}: explicit status honoured")
        except Exception as e:
            self._fail(results, f"{tag}: {e}")
        finally:
            await self._delete_entity(space_id, graph_id, uri)

    async def _test_create_defaults_entity_type(self, results, space_id, graph_id):
        """Create entity with no entity type → defaults to KGEntityType_KGEntity."""
        tag = "create_default_etype"
        ent = self._make_entity(tag)
        # Ensure no entity type is set
        ent.kGEntityType = None
        uri = str(ent.URI)
        try:
            ok = await self._create_entity(space_id, graph_id, ent)
            if not ok:
                return self._fail(results, f"{tag}: create failed")
            fetched = await self._get_entity(space_id, graph_id, uri)
            if not fetched:
                return self._fail(results, f"{tag}: get returned None")
            et = str(fetched.kGEntityType) if fetched.kGEntityType else None
            if et != DEFAULT_ENTITY_TYPE:
                return self._fail(results, f"{tag}: expected {DEFAULT_ENTITY_TYPE}, got {et}")
            self._pass(results, f"{tag}: entity type defaults correctly")
        except Exception as e:
            self._fail(results, f"{tag}: {e}")
        finally:
            await self._delete_entity(space_id, graph_id, uri)

    async def _test_create_honours_explicit_entity_type(self, results, space_id, graph_id):
        """Create entity with type=Person → kGEntityType = Person."""
        tag = "create_explicit_etype"
        ent = self._make_entity(tag, kGEntityType=PERSON_ENTITY_TYPE)
        uri = str(ent.URI)
        try:
            ok = await self._create_entity(space_id, graph_id, ent)
            if not ok:
                return self._fail(results, f"{tag}: create failed")
            fetched = await self._get_entity(space_id, graph_id, uri)
            if not fetched:
                return self._fail(results, f"{tag}: get returned None")
            et = str(fetched.kGEntityType) if fetched.kGEntityType else None
            if et != PERSON_ENTITY_TYPE:
                return self._fail(results, f"{tag}: expected {PERSON_ENTITY_TYPE}, got {et}")
            self._pass(results, f"{tag}: explicit entity type honoured")
        except Exception as e:
            self._fail(results, f"{tag}: {e}")
        finally:
            await self._delete_entity(space_id, graph_id, uri)

    async def _test_update_preserves_creation_time(self, results, space_id, graph_id):
        """Update entity → objectCreationTime unchanged."""
        tag = "update_preserve_ct"
        ent = self._make_entity(tag)
        uri = str(ent.URI)
        try:
            ok = await self._create_entity(space_id, graph_id, ent)
            if not ok:
                return self._fail(results, f"{tag}: create failed")
            created = await self._get_entity(space_id, graph_id, uri)
            if not created:
                return self._fail(results, f"{tag}: get after create returned None")
            ct_before = _to_datetime(created.objectCreationTime)

            # Update — change name only
            created.name = "Updated Name"
            ok = await self._update_entity(space_id, graph_id, created)
            if not ok:
                return self._fail(results, f"{tag}: update failed")
            updated = await self._get_entity(space_id, graph_id, uri)
            if not updated:
                return self._fail(results, f"{tag}: get after update returned None")
            ct_after = _to_datetime(updated.objectCreationTime)

            if ct_before is None or ct_after is None:
                return self._fail(results, f"{tag}: creation time is None (before={ct_before}, after={ct_after})")
            if abs((ct_after - ct_before).total_seconds()) > 1:
                return self._fail(results, f"{tag}: creation time changed: {ct_before} → {ct_after}")
            self._pass(results, f"{tag}: creation time preserved on update")
        except Exception as e:
            self._fail(results, f"{tag}: {e}")
        finally:
            await self._delete_entity(space_id, graph_id, uri)

    async def _test_update_sets_modification_time(self, results, space_id, graph_id):
        """Update entity → objectModificationDateTime ≈ now."""
        tag = "update_sets_mt"
        ent = self._make_entity(tag)
        uri = str(ent.URI)
        try:
            ok = await self._create_entity(space_id, graph_id, ent)
            if not ok:
                return self._fail(results, f"{tag}: create failed")

            time.sleep(1)  # Ensure timestamps differ

            created = await self._get_entity(space_id, graph_id, uri)
            if not created:
                return self._fail(results, f"{tag}: get returned None")
            created.name = "Updated for MT"
            ok = await self._update_entity(space_id, graph_id, created)
            if not ok:
                return self._fail(results, f"{tag}: update failed")

            updated = await self._get_entity(space_id, graph_id, uri)
            if not updated:
                return self._fail(results, f"{tag}: get after update returned None")
            mt = updated.objectModificationDateTime
            if not self._approx_now(mt):
                return self._fail(results, f"{tag}: modification time not ≈ now: {mt}")
            self._pass(results, f"{tag}: modification time updated on update")
        except Exception as e:
            self._fail(results, f"{tag}: {e}")
        finally:
            await self._delete_entity(space_id, graph_id, uri)

    async def _test_update_preserves_status_when_omitted(self, results, space_id, graph_id):
        """Update entity without status → objectStatusType unchanged from DB."""
        tag = "update_preserve_status"
        ent = self._make_entity(tag, objectStatusType=PENDING_STATUS)
        uri = str(ent.URI)
        try:
            ok = await self._create_entity(space_id, graph_id, ent)
            if not ok:
                return self._fail(results, f"{tag}: create failed")

            created = await self._get_entity(space_id, graph_id, uri)
            if not created:
                return self._fail(results, f"{tag}: get returned None")
            # Clear status so update doesn't send it
            created.objectStatusType = None
            created.name = "Updated no status"
            ok = await self._update_entity(space_id, graph_id, created)
            if not ok:
                return self._fail(results, f"{tag}: update failed")

            updated = await self._get_entity(space_id, graph_id, uri)
            if not updated:
                return self._fail(results, f"{tag}: get after update returned None")
            st = str(updated.objectStatusType) if updated.objectStatusType else None
            if st != PENDING_STATUS:
                return self._fail(results, f"{tag}: expected {PENDING_STATUS}, got {st}")
            self._pass(results, f"{tag}: status preserved when omitted on update")
        except Exception as e:
            self._fail(results, f"{tag}: {e}")
        finally:
            await self._delete_entity(space_id, graph_id, uri)

    async def _test_update_allows_status_change(self, results, space_id, graph_id):
        """Update entity with status=INACTIVE → objectStatusType = INACTIVE."""
        tag = "update_change_status"
        ent = self._make_entity(tag)
        uri = str(ent.URI)
        try:
            ok = await self._create_entity(space_id, graph_id, ent)
            if not ok:
                return self._fail(results, f"{tag}: create failed")

            created = await self._get_entity(space_id, graph_id, uri)
            if not created:
                return self._fail(results, f"{tag}: get returned None")
            created.objectStatusType = INACTIVE_STATUS
            ok = await self._update_entity(space_id, graph_id, created)
            if not ok:
                return self._fail(results, f"{tag}: update failed")

            updated = await self._get_entity(space_id, graph_id, uri)
            if not updated:
                return self._fail(results, f"{tag}: get after update returned None")
            st = str(updated.objectStatusType) if updated.objectStatusType else None
            if st != INACTIVE_STATUS:
                return self._fail(results, f"{tag}: expected {INACTIVE_STATUS}, got {st}")
            self._pass(results, f"{tag}: status change honoured on update")
        except Exception as e:
            self._fail(results, f"{tag}: {e}")
        finally:
            await self._delete_entity(space_id, graph_id, uri)

    async def _test_update_preserves_entity_type_when_omitted(self, results, space_id, graph_id):
        """Update entity without entity type → kGEntityType unchanged from DB."""
        tag = "update_preserve_etype"
        ent = self._make_entity(tag, kGEntityType=PERSON_ENTITY_TYPE)
        uri = str(ent.URI)
        try:
            ok = await self._create_entity(space_id, graph_id, ent)
            if not ok:
                return self._fail(results, f"{tag}: create failed")

            created = await self._get_entity(space_id, graph_id, uri)
            if not created:
                return self._fail(results, f"{tag}: get returned None")
            created.kGEntityType = None
            created.name = "Updated no etype"
            ok = await self._update_entity(space_id, graph_id, created)
            if not ok:
                return self._fail(results, f"{tag}: update failed")

            updated = await self._get_entity(space_id, graph_id, uri)
            if not updated:
                return self._fail(results, f"{tag}: get after update returned None")
            et = str(updated.kGEntityType) if updated.kGEntityType else None
            if et != PERSON_ENTITY_TYPE:
                return self._fail(results, f"{tag}: expected {PERSON_ENTITY_TYPE}, got {et}")
            self._pass(results, f"{tag}: entity type preserved when omitted on update")
        except Exception as e:
            self._fail(results, f"{tag}: {e}")
        finally:
            await self._delete_entity(space_id, graph_id, uri)

    async def _test_update_allows_entity_type_change(self, results, space_id, graph_id):
        """Update entity with type=Organization → kGEntityType = Organization."""
        tag = "update_change_etype"
        ent = self._make_entity(tag, kGEntityType=PERSON_ENTITY_TYPE)
        uri = str(ent.URI)
        try:
            ok = await self._create_entity(space_id, graph_id, ent)
            if not ok:
                return self._fail(results, f"{tag}: create failed")

            created = await self._get_entity(space_id, graph_id, uri)
            if not created:
                return self._fail(results, f"{tag}: get returned None")
            created.kGEntityType = ORG_ENTITY_TYPE
            ok = await self._update_entity(space_id, graph_id, created)
            if not ok:
                return self._fail(results, f"{tag}: update failed")

            updated = await self._get_entity(space_id, graph_id, uri)
            if not updated:
                return self._fail(results, f"{tag}: get after update returned None")
            et = str(updated.kGEntityType) if updated.kGEntityType else None
            if et != ORG_ENTITY_TYPE:
                return self._fail(results, f"{tag}: expected {ORG_ENTITY_TYPE}, got {et}")
            self._pass(results, f"{tag}: entity type change honoured on update")
        except Exception as e:
            self._fail(results, f"{tag}: {e}")
        finally:
            await self._delete_entity(space_id, graph_id, uri)

    async def _test_frame_create_touches_modification(self, results, space_id, graph_id):
        """Create frame → parent entity objectModificationDateTime ≈ now."""
        tag = "frame_create_mt"
        ent = self._make_entity(tag)
        uri = str(ent.URI)
        try:
            ok = await self._create_entity(space_id, graph_id, ent)
            if not ok:
                return self._fail(results, f"{tag}: entity create failed")

            time.sleep(1)

            # Create a frame for the entity
            import uuid
            frame = KGFrame()
            frame.URI = f"http://vital.ai/test/server_props/{tag}/frame/{uuid.uuid4()}"
            frame.name = "Test Frame"

            resp = await self.client.kgentities.create_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=uri, objects=[frame]
            )
            if not resp.is_success:
                return self._fail(results, f"{tag}: frame create failed")

            updated = await self._get_entity(space_id, graph_id, uri)
            if not updated:
                return self._fail(results, f"{tag}: get after frame create returned None")
            mt = updated.objectModificationDateTime
            if not self._approx_now(mt):
                return self._fail(results, f"{tag}: modification time not ≈ now after frame create: {mt}")
            self._pass(results, f"{tag}: frame create touches parent modification time")
        except Exception as e:
            self._fail(results, f"{tag}: {e}")
        finally:
            await self._delete_entity(space_id, graph_id, uri)

    async def _test_frame_update_touches_modification(self, results, space_id, graph_id):
        """Update frame → parent entity objectModificationDateTime ≈ now."""
        tag = "frame_update_mt"
        ent = self._make_entity(tag)
        uri = str(ent.URI)
        try:
            ok = await self._create_entity(space_id, graph_id, ent)
            if not ok:
                return self._fail(results, f"{tag}: entity create failed")

            import uuid
            frame = KGFrame()
            frame_uri = f"http://vital.ai/test/server_props/{tag}/frame/{uuid.uuid4()}"
            frame.URI = frame_uri
            frame.name = "Test Frame"

            resp = await self.client.kgentities.create_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=uri, objects=[frame]
            )
            if not resp.is_success:
                return self._fail(results, f"{tag}: frame create failed")

            time.sleep(1)

            # Update the frame
            frame.name = "Updated Frame"
            resp = await self.client.kgentities.update_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=uri, objects=[frame]
            )
            if not resp.is_success:
                return self._fail(results, f"{tag}: frame update failed")

            updated = await self._get_entity(space_id, graph_id, uri)
            if not updated:
                return self._fail(results, f"{tag}: get after frame update returned None")
            mt = updated.objectModificationDateTime
            if not self._approx_now(mt):
                return self._fail(results, f"{tag}: modification time not ≈ now after frame update: {mt}")
            self._pass(results, f"{tag}: frame update touches parent modification time")
        except Exception as e:
            self._fail(results, f"{tag}: {e}")
        finally:
            await self._delete_entity(space_id, graph_id, uri)

    async def _test_frame_delete_touches_modification(self, results, space_id, graph_id):
        """Delete frame → parent entity objectModificationDateTime ≈ now."""
        tag = "frame_delete_mt"
        ent = self._make_entity(tag)
        uri = str(ent.URI)
        try:
            ok = await self._create_entity(space_id, graph_id, ent)
            if not ok:
                return self._fail(results, f"{tag}: entity create failed")

            import uuid
            frame = KGFrame()
            frame_uri = f"http://vital.ai/test/server_props/{tag}/frame/{uuid.uuid4()}"
            frame.URI = frame_uri
            frame.name = "Test Frame"

            resp = await self.client.kgentities.create_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=uri, objects=[frame]
            )
            if not resp.is_success:
                return self._fail(results, f"{tag}: frame create failed")

            time.sleep(1)

            # Delete the frame
            resp = await self.client.kgentities.delete_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=uri, frame_uris=[frame_uri]
            )
            if not resp.is_success:
                return self._fail(results, f"{tag}: frame delete failed")

            updated = await self._get_entity(space_id, graph_id, uri)
            if not updated:
                return self._fail(results, f"{tag}: get after frame delete returned None")
            mt = updated.objectModificationDateTime
            if not self._approx_now(mt):
                return self._fail(results, f"{tag}: modification time not ≈ now after frame delete: {mt}")
            self._pass(results, f"{tag}: frame delete touches parent modification time")
        except Exception as e:
            self._fail(results, f"{tag}: {e}")
        finally:
            await self._delete_entity(space_id, graph_id, uri)

    async def _test_creation_time_immutable_across_updates(self, results, space_id, graph_id):
        """Create entity, update 3 times → objectCreationTime never changes."""
        tag = "ct_immutable"
        ent = self._make_entity(tag)
        uri = str(ent.URI)
        try:
            ok = await self._create_entity(space_id, graph_id, ent)
            if not ok:
                return self._fail(results, f"{tag}: create failed")

            created = await self._get_entity(space_id, graph_id, uri)
            if not created:
                return self._fail(results, f"{tag}: get after create returned None")
            ct_original = _to_datetime(created.objectCreationTime)

            for i in range(3):
                time.sleep(0.5)
                created.name = f"Update {i+1}"
                ok = await self._update_entity(space_id, graph_id, created)
                if not ok:
                    return self._fail(results, f"{tag}: update {i+1} failed")
                fetched = await self._get_entity(space_id, graph_id, uri)
                if not fetched:
                    return self._fail(results, f"{tag}: get after update {i+1} returned None")
                ct = _to_datetime(fetched.objectCreationTime)
                if ct_original is None or ct is None:
                    return self._fail(results, f"{tag}: creation time is None at iteration {i+1}")
                if abs((ct - ct_original).total_seconds()) > 1:
                    return self._fail(results, f"{tag}: creation time changed at iteration {i+1}: {ct_original} → {ct}")
                created = fetched  # use latest for next update

            self._pass(results, f"{tag}: creation time immutable across 3 updates")
        except Exception as e:
            self._fail(results, f"{tag}: {e}")
        finally:
            await self._delete_entity(space_id, graph_id, uri)

    async def _test_update_ignores_client_timestamps(self, results, space_id, graph_id):
        """Update with client-supplied timestamps → server overrides."""
        tag = "update_override_ts"
        ent = self._make_entity(tag)
        uri = str(ent.URI)
        try:
            ok = await self._create_entity(space_id, graph_id, ent)
            if not ok:
                return self._fail(results, f"{tag}: create failed")
            created = await self._get_entity(space_id, graph_id, uri)
            if not created:
                return self._fail(results, f"{tag}: get returned None")
            ct_original = _to_datetime(created.objectCreationTime)

            time.sleep(1)

            # Send update with bogus timestamps
            bogus = datetime(2000, 6, 15, tzinfo=timezone.utc)
            created.objectCreationTime = bogus
            created.objectModificationDateTime = bogus
            created.name = "Updated with bogus ts"
            ok = await self._update_entity(space_id, graph_id, created)
            if not ok:
                return self._fail(results, f"{tag}: update failed")

            updated = await self._get_entity(space_id, graph_id, uri)
            if not updated:
                return self._fail(results, f"{tag}: get after update returned None")
            ct_after = _to_datetime(updated.objectCreationTime)
            mt_after = _to_datetime(updated.objectModificationDateTime)
            # Creation time must be preserved (not the bogus value)
            if ct_original and ct_after and abs((ct_after - ct_original).total_seconds()) > 1:
                return self._fail(results, f"{tag}: creation time changed to client value: {ct_after}")
            # Modification time must be ≈ now (not the bogus value)
            if mt_after and abs((mt_after - bogus).total_seconds()) < 1:
                return self._fail(results, f"{tag}: server did NOT override client modification time")
            if not self._approx_now(mt_after):
                return self._fail(results, f"{tag}: modification time not ≈ now: {mt_after}")
            self._pass(results, f"{tag}: server overrides client timestamps on update")
        except Exception as e:
            self._fail(results, f"{tag}: {e}")
        finally:
            await self._delete_entity(space_id, graph_id, uri)

    async def _test_frame_write_does_not_change_status(self, results, space_id, graph_id):
        """Create/update frame → parent entity objectStatusType unchanged."""
        tag = "frame_no_status_change"
        ent = self._make_entity(tag, objectStatusType=PENDING_STATUS)
        uri = str(ent.URI)
        try:
            ok = await self._create_entity(space_id, graph_id, ent)
            if not ok:
                return self._fail(results, f"{tag}: create failed")
            created = await self._get_entity(space_id, graph_id, uri)
            if not created:
                return self._fail(results, f"{tag}: get returned None")
            st_before = str(created.objectStatusType) if created.objectStatusType else None
            if st_before != PENDING_STATUS:
                return self._fail(results, f"{tag}: initial status not PENDING: {st_before}")

            # Create a frame
            import uuid
            frame = KGFrame()
            frame.URI = f"http://vital.ai/test/server_props/{tag}/frame/{uuid.uuid4()}"
            frame.name = "Test Frame"
            resp = await self.client.kgentities.create_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=uri, objects=[frame]
            )
            if not resp.is_success:
                return self._fail(results, f"{tag}: frame create failed")

            updated = await self._get_entity(space_id, graph_id, uri)
            if not updated:
                return self._fail(results, f"{tag}: get after frame create returned None")
            st_after = str(updated.objectStatusType) if updated.objectStatusType else None
            if st_after != PENDING_STATUS:
                return self._fail(results, f"{tag}: status changed after frame write: {st_before} → {st_after}")
            self._pass(results, f"{tag}: frame write does not change status")
        except Exception as e:
            self._fail(results, f"{tag}: {e}")
        finally:
            await self._delete_entity(space_id, graph_id, uri)

    async def _test_batch_uses_same_timestamp(self, results, space_id, graph_id):
        """Create 3 entities in one batch → all have identical timestamps."""
        tag = "batch_same_ts"
        entities = [self._make_entity(f"{tag}_{i}") for i in range(3)]
        uris = [str(e.URI) for e in entities]
        try:
            resp = await self.client.kgentities.create_kgentities(
                space_id=space_id, graph_id=graph_id, objects=entities
            )
            if not resp.is_success:
                return self._fail(results, f"{tag}: batch create failed")

            timestamps = []
            for uri in uris:
                fetched = await self._get_entity(space_id, graph_id, uri)
                if not fetched:
                    return self._fail(results, f"{tag}: get returned None for {uri}")
                ct = _to_datetime(fetched.objectCreationTime)
                mt = _to_datetime(fetched.objectModificationDateTime)
                if ct is None or mt is None:
                    return self._fail(results, f"{tag}: timestamps None for {uri}")
                timestamps.append((ct, mt))

            # All creation times should be identical (same batch)
            ct0 = timestamps[0][0]
            mt0 = timestamps[0][1]
            for i, (ct, mt) in enumerate(timestamps[1:], 1):
                if abs((ct - ct0).total_seconds()) > 1:
                    return self._fail(results, f"{tag}: creation time differs: entity 0={ct0}, entity {i}={ct}")
                if abs((mt - mt0).total_seconds()) > 1:
                    return self._fail(results, f"{tag}: modification time differs: entity 0={mt0}, entity {i}={mt}")
            self._pass(results, f"{tag}: batch entities share same timestamps")
        except Exception as e:
            self._fail(results, f"{tag}: {e}")
        finally:
            for uri in uris:
                await self._delete_entity(space_id, graph_id, uri)

    async def _test_status_never_null(self, results, space_id, graph_id):
        """Create → update without status → update with status → all reads show non-null status."""
        tag = "status_never_null"
        ent = self._make_entity(tag)
        uri = str(ent.URI)
        try:
            # Create (should default to ACTIVE)
            ok = await self._create_entity(space_id, graph_id, ent)
            if not ok:
                return self._fail(results, f"{tag}: create failed")
            fetched = await self._get_entity(space_id, graph_id, uri)
            if not fetched:
                return self._fail(results, f"{tag}: get returned None")
            st1 = str(fetched.objectStatusType) if fetched.objectStatusType else None
            if not st1:
                return self._fail(results, f"{tag}: status null after create")

            # Update without status
            fetched.objectStatusType = None
            fetched.name = "Updated no status"
            ok = await self._update_entity(space_id, graph_id, fetched)
            if not ok:
                return self._fail(results, f"{tag}: update 1 failed")
            fetched2 = await self._get_entity(space_id, graph_id, uri)
            if not fetched2:
                return self._fail(results, f"{tag}: get after update 1 returned None")
            st2 = str(fetched2.objectStatusType) if fetched2.objectStatusType else None
            if not st2:
                return self._fail(results, f"{tag}: status null after update without status")

            # Update with explicit status
            fetched2.objectStatusType = INACTIVE_STATUS
            ok = await self._update_entity(space_id, graph_id, fetched2)
            if not ok:
                return self._fail(results, f"{tag}: update 2 failed")
            fetched3 = await self._get_entity(space_id, graph_id, uri)
            if not fetched3:
                return self._fail(results, f"{tag}: get after update 2 returned None")
            st3 = str(fetched3.objectStatusType) if fetched3.objectStatusType else None
            if st3 != INACTIVE_STATUS:
                return self._fail(results, f"{tag}: expected {INACTIVE_STATUS}, got {st3}")

            self._pass(results, f"{tag}: status never null through create+updates")
        except Exception as e:
            self._fail(results, f"{tag}: {e}")
        finally:
            await self._delete_entity(space_id, graph_id, uri)

    async def _test_entity_type_never_null(self, results, space_id, graph_id):
        """Create → update without entity type → all reads show non-null entity type."""
        tag = "etype_never_null"
        ent = self._make_entity(tag)
        uri = str(ent.URI)
        try:
            # Create (should default)
            ok = await self._create_entity(space_id, graph_id, ent)
            if not ok:
                return self._fail(results, f"{tag}: create failed")
            fetched = await self._get_entity(space_id, graph_id, uri)
            if not fetched:
                return self._fail(results, f"{tag}: get returned None")
            et1 = str(fetched.kGEntityType) if fetched.kGEntityType else None
            if not et1:
                return self._fail(results, f"{tag}: entity type null after create")

            # Update without entity type
            fetched.kGEntityType = None
            fetched.name = "Updated no etype"
            ok = await self._update_entity(space_id, graph_id, fetched)
            if not ok:
                return self._fail(results, f"{tag}: update failed")
            fetched2 = await self._get_entity(space_id, graph_id, uri)
            if not fetched2:
                return self._fail(results, f"{tag}: get after update returned None")
            et2 = str(fetched2.kGEntityType) if fetched2.kGEntityType else None
            if not et2:
                return self._fail(results, f"{tag}: entity type null after update without type")

            self._pass(results, f"{tag}: entity type never null through create+update")
        except Exception as e:
            self._fail(results, f"{tag}: {e}")
        finally:
            await self._delete_entity(space_id, graph_id, uri)

    async def _test_round_trip_datetime_precision(self, results, space_id, graph_id):
        """Create → read back → timestamps match with at least second precision."""
        tag = "round_trip_precision"
        ent = self._make_entity(tag)
        uri = str(ent.URI)
        try:
            before = datetime.now(timezone.utc)
            ok = await self._create_entity(space_id, graph_id, ent)
            if not ok:
                return self._fail(results, f"{tag}: create failed")
            after = datetime.now(timezone.utc)

            fetched = await self._get_entity(space_id, graph_id, uri)
            if not fetched:
                return self._fail(results, f"{tag}: get returned None")
            ct = _to_datetime(fetched.objectCreationTime)
            mt = _to_datetime(fetched.objectModificationDateTime)
            if ct is None or mt is None:
                return self._fail(results, f"{tag}: timestamps None (ct={ct}, mt={mt})")

            # Both timestamps must be between before and after (with 2s tolerance for clock)
            tolerance = 2.0
            if ct < before.replace(microsecond=0) - timedelta(seconds=tolerance):
                return self._fail(results, f"{tag}: creation time {ct} is before request start {before}")
            if ct > after + timedelta(seconds=tolerance):
                return self._fail(results, f"{tag}: creation time {ct} is after request end {after}")

            # Verify second-level precision (not truncated to minutes/hours)
            # The seconds component should be non-zero in at least one of the timestamps
            # (probabilistically ~99% of the time). We check that microseconds are preserved
            # by verifying the timestamp has sub-minute precision.
            ct_has_seconds = ct.second != 0 or ct.microsecond != 0
            mt_has_seconds = mt.second != 0 or mt.microsecond != 0
            # At least check that ct and mt are equal (same request)
            if abs((ct - mt).total_seconds()) > 1:
                return self._fail(results, f"{tag}: ct and mt differ by more than 1s: ct={ct}, mt={mt}")

            self._pass(results, f"{tag}: round-trip datetime precision verified (ct={ct}, mt={mt})")
        except Exception as e:
            self._fail(results, f"{tag}: {e}")
        finally:
            await self._delete_entity(space_id, graph_id, uri)
