from app.core.result import Ok
from app.domain.aggregates.system_instruction import SystemInstruction
from app.domain.value_objects.ai_provider import AIProvider
from app.domain.value_objects.system_instruction_id import SystemInstructionId


class TestSystemInstruction:
    def test_create(self):
        """Test creating a new SystemInstruction."""
        provider = AIProvider.GEMINI
        instruction_text = "You are a helpful assistant."
        is_active = True

        result = SystemInstruction.create(
            provider=provider,
            instruction=instruction_text,
            is_active=is_active,
        )

        assert isinstance(result, Ok)
        instruction = result.unwrap()

        assert isinstance(instruction.id, SystemInstructionId)
        assert instruction.provider == provider
        assert instruction.instruction == instruction_text
        assert instruction.is_active == is_active

    def test_reconstruct(self):
        """Test reconstructing an existing SystemInstruction."""
        id_result = SystemInstructionId.generate()
        assert isinstance(id_result, Ok)
        instruction_id = id_result.unwrap()

        provider = AIProvider.GPT
        instruction_text = "Be concise."
        is_active = False

        instruction = SystemInstruction.reconstruct(
            id=instruction_id,
            provider=provider,
            instruction=instruction_text,
            is_active=is_active,
        )

        assert instruction.id == instruction_id
        assert instruction.provider == provider
        assert instruction.instruction == instruction_text
        assert instruction.is_active == is_active

    def test_activate_deactivate(self):
        """Test activating and deactivating."""
        result = SystemInstruction.create(AIProvider.GEMINI, "Test")
        instruction = result.unwrap()

        # Default is inactive (based on default arg in create which is False)
        # Wait, let's check the default in create: is_active: bool = False.
        assert not instruction.is_active

        instruction.activate()
        assert instruction.is_active

        instruction.deactivate()
        assert not instruction.is_active
