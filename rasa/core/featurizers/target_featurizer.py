from abc import abstractmethod
from typing import List, Text, Dict, Optional, Any

import numpy as np
from rasa.core.featurizers import state_featurizer

from rasa.core.featurizers.extractor import Target  # TODO:
from rasa.core.featurizers.state_featurizer import StateFeaturizer
from rasa.nlu.extractors.extractor import EntityTagSpec
from rasa.nlu.utils import bilou_utils
from rasa.shared.core.domain import Domain
from rasa.shared.core import state as state_utils
from rasa.shared.nlu.constants import ENTITY_TAGS
from rasa.shared.nlu.interpreter import NaturalLanguageInterpreter
from rasa.shared.nlu.training_data.message import Message
from rasa.shared.nlu.training_data.features import Features
from rasa.nlu.utils.bilou_utils import BILOU_PREFIXES
from rasa.utils.tensorflow import model_data_utils

# TODO: compose a TargetFeaturizer from ItemFeaturizers...
#


class TargetItemFeaturizer:
    @abstractmethod
    def setup(
        self,
        domain: Domain,
        state_featurizer: StateFeaturizer,  # TODO: might need to set later?
    ) -> None:
        pass

    @abstractmethod
    def is_ready(self) -> bool:
        pass

    def raise_if_not_ready(self) -> None:
        if not self.is_ready():
            raise RuntimeError(
                f"Expected {self.__class__.__name__} has been `setup()`."
            )

    def raise_if_ready(self) -> None:
        if self.is_ready():
            raise RuntimeError(
                f"Expected {self.__class__.__name__} had not been `setup()` before."
            )

    @abstractmethod
    def featurize(
        self, item: Text, interpreter: Optional[NaturalLanguageInterpreter]
    ) -> List[Dict[Text, "Features"]]:
        pass


class InterpreterFeaturesForActions(TargetItemFeaturizer):
    """
    """

    def __init__(
        self,
        state_featurizer: Optional[StateFeaturizer],  # TODO: might need to set later?
        action_texts: Optional[List[Text]],
    ) -> None:
        self.state_featurizer = state_featurizer
        self.action_texts = action_texts

    def setup(self, domain: Domain, state_featurizer: StateFeaturizer) -> None:
        """
        NOTE: domain and interpreter might not be known during instantiation
        """
        self.action_texts = domain.action_texts
        self.state_featurizer = state_featurizer

    def is_ready(self) -> bool:
        return (
            (state_featurizer is not None)
            and (state_featurizer.is_ready())
            and self.action_texts
        )

    def featurize(
        self, action: Text, interpreter: Optional[NaturalLanguageInterpreter] = None,
    ) -> Dict[Text, "Features"]:
        """

        TODO: accept List here to be able to "concat" feaures here already?

        TODO: must be possible to get rid of the interpreter check here / pass the
        "correct" interpreter right away...

        """
        self.raise_if_not_ready()
        interpreter = self.state_featurizer.check_and_replace_interpreter_if_needed(
            interpreter
        )

        sub_state = state_utils.create_substate_from_action(
            action, as_text=(action in self.action_texts)
        )
        return self.state_featurizer.featurize_substate_via_interpreter(
            sub_state, interpreter=interpreter
        )


class ActionsToIndices(TargetItemFeaturizer):
    """
    NOTE: because _create_label_id ...
    """

    def __init__(
        self,
        state_featurizer: Optional[StateFeaturizer],
        action_texts: Optional[List[Text]],
    ) -> None:
        self.state_featurizer = state_featurizer  # TODO: might need to set later?
        self.action_texts = action_texts

    def setup(self, domain: Domain, state_featurizer: StateFeaturizer) -> None:
        """
        NOTE: domain and interpreter might not be known during instantiation
        """
        self.action_texts = domain.action_texts
        self.state_featurizer = state_featurizer

    def is_ready(self) -> bool:
        return (
            (state_featurizer is not None)
            and (state_featurizer.is_ready())
            and self.action_texts
        )

    def featurize(
        self, action: Text, interpreter: Optional[NaturalLanguageInterpreter] = None,
    ) -> Dict[Text, "Features"]:
        # TODO: accept List here to be able to "concat" feaures here already?
        ...

    @staticmethod
    def convert_actions_to_ids(action: Text, domain: Domain) -> np.ndarray:
        """
        """
        # TODO:  all domainrelated to index stuff should be generated by domain,
        # handed over to component to store, and then when components are loaded
        # validated whether they still match the domain / each other...
        # (if a domain is loaded?)

        # store labels in numpy arrays so that it corresponds to np arrays of input
        # features
        return domain.index_for_action(action)


class EntityDataFeaturizer(TargetItemFeaturizer):
    """
    # TODO/FIXME: why is this different from what state_featurizer does?
    """

    def __init__(
        self, bilou_tagging: bool, encoding_spec: Optional[EntityTagSpec] = None
    ) -> None:
        """

        """
        self.bilou_tagging = bilou_tagging  # this should be known in advance?
        self.encoding_spec = encoding_spec

    def setup(self, domain: Domain, state_featurizer: StateFeaturizer,) -> None:
        """
        NOTE: domain might not be known during instantiation (?)

        """
        entities = sorted(domain.entity_states)
        if self.bilou_tagging:
            tag_id_index_mapping = {
                f"{prefix}{tag}": idx_1 * len(BILOU_PREFIXES) + idx_2 + 1
                for tag, idx_1 in enumerate(entities)
                for idx_2, prefix in enumerate(BILOU_PREFIXES)
            }
        else:
            tag_id_index_mapping = {
                tag: idx + 1  # +1 to keep 0 for the NO_ENTITY_TAG
                for tag, idx in enumerate(entities)
            }

        # NO_ENTITY_TAG corresponds to non-entity which should correspond to 0 index
        # needed for correct prediction for padding
        tag_id_index_mapping[NO_ENTITY_TAG] = 0

        # TODO
        #  The entity states used to create the tag-idx-mapping contains the
        #  entities and the concatenated entity and roles/groups. We do not
        #  distinguish between entities and roles/groups right now.
        #  we return a list to anticipate that
        self.encoding_spec = EntityTagSpec(
            tag_name=ENTITY_ATTRIBUTE_TYPE,
            tags_to_ids=tag_id_index_mapping,
            ids_to_tags={value: key for key, value in tag_id_index_mapping.items()},
            num_tags=len(tag_id_index_mapping),
        )

    def is_ready(self) -> bool:
        return self.encoding_spec is not None

    def featurize(
        self,
        entity_data: Dict[Text, Any],  # TODO/FIXME: this is message data...
        interpreter: NaturalLanguageInterpreter,
    ) -> Dict[Text, List["Features"]]:
        """Encode the given entity data with the help of the given interpreter.

        Produce numeric entity tags for tokens.

        Args:
            entity_data: The dict containing the text and entity labels and locations
            interpreter: The interpreter used to encode the state
            #bilou_tagging: indicates whether BILOU tagging should be used or not

        Returns:
            A dictionary of entity type to list of features.
        """
        # TODO
        #  The entity states used to create the tag-idx-mapping contains the
        #  entities and the concatenated entity and roles/groups. We do not
        #  distinguish between entities and roles/groups right now.
        if (
            not entity_data
            or not self.encoding_specs
            or self.encoding_specs.num_tags < 2
        ):
            # we cannot build a classifier with fewer than 2 classes
            return {}

        message = interpreter.featurize_message(Message(entity_data))

        if not message:
            return {}

        if self.bilou_tagging:
            bilou_utils.apply_bilou_schema_to_message(message)

        return {
            ENTITY_TAGS: [
                model_data_utils.get_tag_ids(
                    message, self.encoding_specs, self.bilou_tagging
                )
            ]
        }


class TargetsFeaturizer:
    """
    NOTE: Why not just state featurizer? Because for some architectures we might not
    want/need the targets to be featurized via the interpreter.
    """

    def __init__(
        self,
        action_featurizer: Optional[TargetItemFeaturizer],
        entity_featurizer: Optional[TargetItemFeaturizer],
    ):
        self.action_featurizer = action_featurizer
        self.entity_featurizer = entity_featurizer
