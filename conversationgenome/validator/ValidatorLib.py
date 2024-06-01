verbose = False

import copy
import random
import asyncio
import math
import os
import numpy as np


from conversationgenome.utils.Utils import Utils
from conversationgenome.ConfigLib import c

from conversationgenome.miner.MinerLib import MinerLib
from conversationgenome.conversation.ConvoLib import ConvoLib
from conversationgenome.llm.LlmLib import LlmLib
from conversationgenome.mock.MockBt import MockBt
from conversationgenome.analytics.PrometheusLib import instrument

bt = None
try:
    import bittensor as bt
except:
    if verbose:
        print("bittensor not installed")
    bt = MockBt()

if c.get('env', 'FORCE_LOG') == 'debug':
    bt.logging.enable_debug(True)
elif c.get('env', 'FORCE_LOG') == 'info':
    bt.logging.enable_default(True)

import wandb

# xxx Refactor to multiple participants. Make abstract class?
proto = {
    "interests_of_q": [],
    "hobbies_of_q": [],
    "personality_traits_of_q": [],
    "interests_of_a": [],
    "hobbies_of_a": [],
    "personality_traits_of_a": [],
}


class ValidatorLib:
    mode = "test" # test|local_llm|openai|anthropic
    hotkey = "v1234"
    verbose = False

    def __init__(self):
        super(ValidatorLib, self).__init__()

    async def begin_log_wandb(self, c_guid):
        api = wandb.Api()
        wandb_api_key = c.get("env", "WANDB_API_KEY")
        if not wandb_api_key:
            raise ValueError("Please log in to wandb using `wandb login` or set the WANDB_API_KEY environment variable.")
        run = 5
        #bt.logging.info("INIT", wandb_api_key)
        epochs = 10
        wandb.init(
              # Set the project where this run will be logged
              project="cgp_test_run",
              # We pass a run name (otherwise it’ll be randomly assigned, like sunshine-lollypop-10)
              name=f"conversationgenome/cguid_{c_guid}",
              # Track hyperparameters and run metadata
              config={
              "learning_rate": 0.02,
              "architecture": "CNN",
              "dataset": "CIFAR-100",
              "epochs": epochs,
        })

    async def end_log_wandb(self, c_guid):
        # Mark the run as finished
        wandb.finish()

    async def log_wandb_finish(self):
        epochs = 2
        offset = random.random() / 5
        for epoch in range(2, epochs):
            acc = 1 - 2 ** -epoch - random.random() / epoch - offset
            loss = 2 ** -epoch + random.random() / epoch + offset

            wandb.log({"acc": acc, "loss": loss})

        # Mark the run as finished
        wandb.finish()


    async def reserve_conversation(self, minConvWindows = 1, batch_num=None):
        import time
        out = None
        # Validator requests a full conversation from the API
        full_conversation = await self.getConvo()
        if self.verbose:
            bt.logging.info("full_conversation", full_conversation)

        if full_conversation:
            conversation_guid = str(Utils.get(full_conversation, "guid"))
            num_lines = len(Utils.get(full_conversation, 'lines', []))

            bt.logging.info(f"Reserved conversation ID: {conversation_guid} with {num_lines} lines. Sending to {c.get('env','LLM_TYPE')} LLM...")

            # Do overview tagging and generate base participant profiles
            full_conversation_metadata = await self.generate_full_convo_metadata(full_conversation)
            if not full_conversation_metadata:
                bt.logging.error(f"ERROR:927402. No metadata for conversation returned to validator. Aborting.")
                validatorHotkey = "HK-FAIL"
                await self.put_convo("NO-TAGS", conversation_guid, {"tags":[], "vectors":[]}, type="validator", batch_num=batch_num)

                return None
            full_conversation_tags = Utils.get(full_conversation_metadata, "tags", [])
            bt.logging.info(f"Found {len(full_conversation_tags)} tags in FullConvo")

            log_path = c.get('env', 'SCORING_DEBUG_LOG')
            if not Utils.empty(log_path):
                Utils.append_log(log_path, f"Validator found full convo tags {full_conversation_tags} in FullConvo")

            # Make sure there are enough tags to make processing worthwhile
            minValidTags = self.validateMinimumTags(full_conversation_tags)
            if minValidTags:
                # Break the full conversation up into overlapping conversation windows
                convoWindows = self.getConvoWindows(full_conversation)
                if len(convoWindows) > minConvWindows:
                    out = (full_conversation, full_conversation_metadata, convoWindows)
                else:
                    bt.logging.info(f"Not enough convo windows -- only {len(convoWindows)}. Passing.")
                    out = None
            else:
                bt.logging.info("Not enough valid tags for conversation. Passing.")
                out = None
            #await self.end_log_wandb(conversation_guid)
            #return None
            return out
        else:
            bt.logging.error(f"ERROR:9879432: No conversation returned from API. Aborting.")
        return None

    @instrument
    async def getConvo(self):
        hotkey = self.hotkey
        cl = ConvoLib()
        convo = await cl.get_conversation(hotkey)
        return convo

    async def put_convo(self, hotkey, c_guid, data, type="validator", batch_num=None, window=None):
        cl = ConvoLib()
        convo = await cl.put_conversation(hotkey, c_guid, data, type=type, batch_num=batch_num, window=window)
        return convo

    @instrument
    def getConvoWindows(self, fullConvo):
        minLines = c.get("convo_window", "min_lines", 5)
        maxLines = c.get("convo_window", "max_lines", 10)
        overlapLines = c.get("convo_window", "overlap_lines", 2)

        windows = Utils.split_overlap_array(fullConvo['lines'], size=maxLines, overlap=overlapLines)
        if len(windows) < 2:
            windows = Utils.split_overlap_array(fullConvo['lines'], size=minLines, overlap=overlapLines)

        # TODO: Write convo windows into local database with full convo metadata
        return windows


    @instrument
    async def generate_full_convo_metadata(self, convo):
        if self.verbose:
            bt.logging.info(f"Execute generate_full_convo_metadata for participants {convo['participants']}")
        else:
            bt.logging.info(f"Execute generate_full_convo_metadata")

        llml = LlmLib()
        result = await llml.conversation_to_metadata(convo)
        if not result:
            bt.logging.error(f"ERROR:2873226353. No conversation metadata returned. Aborting.")
            return None
        if not Utils.get(result, 'success'):
            bt.logging.error(f"ERROR:2873226354. Conversation metadata failed: {result}. Aborting.")
            return None

        tags = result['tags']
        vectors = Utils.get(result, 'vectors', {})
        data = {
            "participantProfiles": convo['participants'],
            "tags": tags,
            "vectors": vectors,
        }
        return data

    @instrument
    async def send_to_miners(self, conversation_guid, window_idx, conversation_window, miner_uids):
        bt.logging.info(f"Send to conversation {conversation_guid} / {window_idx} to miners: {miner_uids}")
        results = []
        ml = MinerLib()
        tasks = [asyncio.create_task(ml.do_mining(conversation_guid, window_idx, conversation_window, minerUid)) for minerUid in miner_uids]
        await asyncio.wait(tasks)
        for task in tasks:
            results.append(task.result())
        return results

    def validateMinimumTags(self, tags):
        # TODO: Validate tags
        #bt.logging.info("Validating tags", tags)
        return True

    def selectStage1Miners(self, uids, num=3):
        # TODO: Move to MockBt
        selectedMiners = random.sample(uids, num)
        return selectedMiners

    async def outputEmissions(self, convoId, windowId, emissionRewards):
        bt.logging.info("EMISSIONS for %d window %d" % (convoId, windowId), emissionRewards)

    async def send_windows_to_test_miners(self, windows, full_conversation=None, full_conversation_metadata=None):
        conversation_guid = Utils.get(full_conversation, "uid")
        participantProfiles = Utils.get(full_conversation_metadata, "participantProfiles", [])
        full_conversationTags = Utils.get(full_conversation_metadata, "tags", [])
        full_conversationTagVectors = Utils.get(full_conversation_metadata, "tag_vectors", {})

        if self.verbose:
            bt.logging.info("full_conversationTagVectors", full_conversationTagVectors)
        vectorNeightborhood = []
        for key, full_conversationTagVector in full_conversationTagVectors.items():
            #bt.logging.info("full_conversationTagVector", key, full_conversationTagVector)
            vectorNeightborhood.append(full_conversationTagVector['vectors'])
            #bt.logging.info("num vectors", len(full_conversationTagVector['vectors']))

        #bt.logging.info("vectorNeightborhood LEN", len(vectorNeightborhood))
        semantic_neighborhood = np.mean(vectorNeightborhood, axis=0)
        #bt.logging.info("Full convo semantic_neighborhood", semantic_neighborhood)

        if self.verbose:
            bt.logging.info("Full convo tags", full_conversationTags)

        # Loop through rows in db
        success = True
        for idx, window in enumerate(windows):
            # Pick initial minors
            minersPerWindow = c.get("validator", "miners_per_window", 3)
            uids = [1,2,3,4,5,6,7,8,9]
            miners = self.selectStage1Miners(uids, minersPerWindow)
            # Send first window to miners
            miner_results = await self.send_to_miners(conversation_guid, idx, window, miners)
            #bt.logging.info("Miner results", minerResults)
            # TODO: Each miner returns data, write data into local db
            # TODO: Write up incomplete errors, such as if timeout happens for miner, send to another miner

            # When all miners have returned data for convo window, score compared to full convo tags
            for minerResult in minerResults:
                uid = Utils.get(minerResult, 'uid')
                tags = Utils.get(minerResult, 'tags')
                vectors = Utils.get(minerResult, 'vectors')
                #bt.logging.info("VECTORS", vectors)
                compareResults = Utils.compare_arrays(full_conversationTags, tags)
                compareResults['total_1'] = len(full_conversationTags)
                compareResults['total_2'] = len(tags)
                #bt.logging.info("COMPARE", compareResults)
                scoreToFullConvo = await self.calculate_base_score(compareResults)
                minerResult['score'] = scoreToFullConvo
                similarity_scores = []
                uniqueTags = compareResults['unique_2']
                if len(uniqueTags) > 0:
                    for unique_tag in uniqueTags:
                        if unique_tag in vectors:
                            tagVectors = vectors[unique_tag]['vectors']
                            #bt.logging.info("VECTOR", unique_tag, tagVectors[0:2])
                            # similarity_score
                            #  0 = orthogonal (perpendicular), no similarity
                            #  1 = identical in orientation, maximum similarity
                            # -1 = diametrically opposed, maximum dissimilarity
                            similarity_score = 0
                            if not Utils.is_empty_vector(tagVectors):
                                similarity_score = np.dot(semantic_neighborhood, tagVectors) / (np.linalg.norm(semantic_neighborhood) * np.linalg.norm(tagVectors))
                                #bt.logging.info(f"Similarity score between the content and the tag '{unique_tag}': {similarity_score}")
                            similarity_scores.append(similarity_score)
                    bt.logging.info("MEDIAN similarity_score of %d unique tags for miner %s" % (len(uniqueTags), str(uid)), np.median(similarity_scores), similarity_scores)
                else:
                    bt.logging.info( "No unique tags for miner %s" % (str(uid)) )

            await self.calculate_emission_rewards(minerResults, 'score')

            rewards = {}
            for minerResult in minerResults:
                rewards[minerResult['uid']] = minerResult['reward']
            # Send emissions
            await self.outputEmissions(1, idx, rewards)

        if success == True:
            cl = ConvoLib()
            await cl.markConversionComplete(self.hotkey, cguid)

    async def neighborhood_test(self):
        bt.logging.info("Quick test for semantic neighborhood with vectors")
        llml = LlmLib()
        await llml.test_neighborhood()

    async def llm_test(self):
        bt.logging.info("Quick test for LLM")
        llml = LlmLib()
        await llml.test_tagging()


