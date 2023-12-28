import torch
from math import *
import re
import numpy as np
from nltk import word_tokenize
from transformers import AutoTokenizer, AutoModel
from transformers import RobertaTokenizer, RobertaModel
from torch import Tensor
import torch.nn.functional as F


def preprocessing(text):
    '''
    Note, this preprocessing function should be applied to any text before getting its embedding.
    Input: text as string

    Output: removing newline, latex $$, and common website urls.
    '''
    pattern = r"(((https?|ftp)://)|(www.))[^\s/$.?#].[^\s]*"
    text = re.sub(pattern, '', text)
    return text.replace("\n", " ").replace("$", "")


def average_pool(last_hidden_states: Tensor,
                 attention_mask: Tensor) -> Tensor:
    last_hidden = last_hidden_states.masked_fill(~attention_mask[..., None].bool(), 0.0)
    return last_hidden.sum(dim=1) / attention_mask.sum(dim=1)[..., None]


def load_model_arguana(model_name, cuda=None, model_path=None):
    """
    loading models/tokenizers based on model_name, also based on cuda option specify whether DataParallel.
    Input: cuda option is a string, e.g. "1,3,5" specify cuda1, cuda3, and cuda5 will be used, store parameters on cuda1.
    """
    if model_name == "ernie":
        tokenizer = AutoTokenizer.from_pretrained("nghuyong/ernie-2.0-large-en")
        if model_path is None:
            model = AutoModel.from_pretrained("nghuyong/ernie-2.0-large-en")
        else:
            model_parallel = torch.load(f"./training/model_checkpoints/{model_path}.pth", map_location='cpu')
            model = model_parallel.module
        model.eval()

    elif model_name in ["e5", "e5v3"]:
        tokenizer = AutoTokenizer.from_pretrained('intfloat/e5-large-v2')
        if model_path is None:
            model = AutoModel.from_pretrained('intfloat/e5-large-v2')
        else:
            model_parallel = torch.load(f"./training/model_checkpoints/{model_path}.pth", map_location='cpu')
            model = model_parallel.module
        model.eval()

    elif model_name == "simcse":
        tokenizer = AutoTokenizer.from_pretrained("princeton-nlp/sup-simcse-roberta-large")
        if model_path is None:
            model = AutoModel.from_pretrained("princeton-nlp/sup-simcse-roberta-large")
        else:
            model_parallel = torch.load(f"./training/model_checkpoints/{model_path}.pth", map_location='cpu')
            model = model_parallel.module
        model.eval()

    elif model_name == "roberta":
        tokenizer = RobertaTokenizer.from_pretrained('roberta-large')
        if model_path is None:
            model = RobertaModel.from_pretrained('roberta-large')
        else:
            model_parallel = torch.load(f"./training/model_checkpoints/{model_path}.pth", map_location='cpu')
            model = model_parallel.module
        model.eval()

    elif model_name == "simlm":
        tokenizer = AutoTokenizer.from_pretrained('intfloat/simlm-base-msmarco-finetuned')
        if model_path is None:
            model = AutoModel.from_pretrained('intfloat/simlm-base-msmarco-finetuned')
        else:
            model_parallel = torch.load(f"./training/model_checkpoints/{model_path}.pth", map_location='cpu')
            model = model_parallel.module
        model.eval()

    elif model_name == "spladev2":
        tokenizer = AutoTokenizer.from_pretrained('naver/splade_v2_distil')
        if model_path is None:
            model = AutoModel.from_pretrained('naver/splade_v2_distil')

        else:
            model_parallel = torch.load(f"./training/model_checkpoints/{model_path}.pth", map_location='cpu')
            model = model_parallel.module
        model.eval()

    elif model_name == "scibert":
        tokenizer = AutoTokenizer.from_pretrained('allenai/scibert_scivocab_cased')
        if model_path is None:
            model = AutoModel.from_pretrained('allenai/scibert_scivocab_cased')
        else:
            model_parallel = torch.load(f"./training/model_checkpoints/{model_path}.pth", map_location='cpu')
            model = model_parallel.module
        model.eval()

    elif model_name == "specterv2":
        tokenizer = AutoTokenizer.from_pretrained('allenai/specter2_base')
        if model_path is None:
            model = AutoModel.from_pretrained('allenai/specter2_base')
            model.load_adapter("allenai/specter2", source="hf", load_as="specter2", set_active=True)
        else:
            model_parallel = torch.load(f"./training/model_checkpoints/{model_path}.pth", map_location='cpu')
            model = model_parallel.module
            print(f"Loading : ./training/model_checkpoints/{model_path}_adapter")
            model.load_adapter(f"./training/model_checkpoints/{model_path}_adapter", load_as="specter2",
                               set_active=True)
        model.eval()

    if cuda != "cpu":
        torch.cuda.set_device(int(cuda.split(",")[0]))

        model.to("cuda")
        cuda_list = cuda.split(",")
        cuda_num = len(cuda_list)
        if cuda_num > 1:
            model = torch.nn.DataParallel(model, device_ids=[int(idx) for idx in cuda_list])
    else:
        print("Running model on CPU...")
    num_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"{model_name} model parameters: {int(num_params / 1000000)} millions.")
    return model, tokenizer


def optimal_batch_size(model_name, model, tokenizer, text, cuda_num, cuda, bs):
    """
    Input model: loaded model
          tokenizer: associated tokenizer
          text: a list of strings, each string is either a query or an abstract
          cuda_num: int, number of cuda available
          bs: bs is the user defined maximum batch size to try
    Return a stable batch_size that could be used for given configuration.
    """
    if model_name in ["ernie", "e5v3", "e5", "roberta_retrain", "roberta",
                      "simcse"]:  
        bs = bs // 3
    if model_name in ["sentbert", "ance"]:
        len_token = []
        for t in text:
            inputs = word_tokenize(preprocessing(t))
            len_token.append(len(inputs))
        sample_text = preprocessing(text[np.argmax(len_token)])
        print(f"maximum tokenized text length {max(len_token)}")
        batch_size = cuda_num * bs * 5
    else:
        len_token = []
        for t in text:
            inputs = tokenizer(preprocessing(t))
            len_token.append(len(inputs["input_ids"]))
        sample_text = preprocessing(text[np.argmax(len_token)])
        print(f"maximum tokenized text length {max(len_token)}")
        batch_size = cuda_num * bs
    while batch_size > 0:
        sample_batch = [sample_text] * batch_size
        try:
            print(f"Trying batch size : {batch_size}")
            inputs = tokenization(model_name, tokenizer, sample_batch)
            embedding = encoding(model_name, model, inputs, cuda)
            print(f"Optimal batch size is {batch_size}")

            return batch_size
        except RuntimeError as e:
            if "memory" in str(e).lower():
                batch_size -= cuda_num
            else:
                raise RuntimeError("Other issues in the model implementation")
    raise ValueError("Cuda memory does not support batch processing")





def tokenization(model_name, tokenizer, text):
    '''
    Different tokenization procedures based on different models.

    Input: text as list of strings, if cpu option then list has length 1.
    Return: tokenized inputs, could be dictionary for BERT models.
    '''
    if model_name in ["sentbert", "ance"]:
        return text
    elif model_name in ["e5v3", "ernie", "simlm", "spladev2", "scibert", "colbertv2", "specterv2", "e5", "simcse",
                        "scibertID", "roberta_retrain", "roberta"]:
        inputs = tokenizer(text, padding="longest", truncation=True, max_length=512, return_tensors="pt")


    return inputs


def encoding(model_name, model, inputs, cuda):
    '''
    Different encoding procedures based on different models.
    Input: inputs are tokenized inputs in specific form
    Return: a numpy ndarray embedding on cpu.

    # inputs are tokenized text
    # model is the loaded model
    # model_name is used to help the function know what to do
    '''
    if cuda != "cpu":
        device = "cuda"
    else:
        device = "cpu"
    with torch.no_grad():
        if model_name in ["ernie"]:
            input_ids = inputs['input_ids'].to(device)
            attention_mask = inputs['attention_mask'].to(device)
            embeddings = model(input_ids, attention_mask=attention_mask)
            output = embeddings.pooler_output.detach().cpu()
        #             del input_ids, attention_mask, embeddings
        #             torch.cuda.empty_cache()
        elif model_name in ["e5", "e5v3"]:
            input_ids = inputs['input_ids'].to(device)
            assert input_ids.shape[1] <= 512
            token_type_ids = inputs['token_type_ids'].to(device)
            attention_mask = inputs['attention_mask'].to(device)

            new_batch_dict = {}
            new_batch_dict["input_ids"] = input_ids
            new_batch_dict["token_type_ids"] = token_type_ids
            new_batch_dict["attention_mask"] = attention_mask

            outputs = model(**new_batch_dict)
            embeddings = average_pool(outputs.last_hidden_state, new_batch_dict['attention_mask'])
            embeddings = F.normalize(embeddings, p=2, dim=1)

            output = embeddings.detach().cpu()

        elif model_name in ["simcse", "ernie", "scibert", "scibertID"]:
            input_ids = inputs['input_ids'].to(device)
            assert input_ids.shape[1] <= 512
            attention_mask = inputs['attention_mask'].to(device)
            outputs = model(input_ids, attention_mask=attention_mask)
            outputs = outputs.pooler_output
            outputs = F.normalize(outputs, p=2, dim=1)

            output = outputs.detach().cpu()

        elif model_name in ["roberta", "roberta_retrain"]:
            input_ids = inputs['input_ids'].to(device)
            assert input_ids.shape[1] <= 512
            attention_mask = inputs['attention_mask'].to(device)

            new_batch_dict = {}
            new_batch_dict["input_ids"] = input_ids
            new_batch_dict["attention_mask"] = attention_mask

            outputs = model(**new_batch_dict)
            embeddings = average_pool(outputs.last_hidden_state, new_batch_dict['attention_mask'])
            embeddings = F.normalize(embeddings, p=2, dim=1)

            output = embeddings.detach().cpu()

        #             del input_ids, attention_mask, new_batch_dict, outputs, embeddings
        #             torch.cuda.empty_cache()

        elif model_name in ["simlm", "specterv2"]:
            input_ids = inputs['input_ids'].to(device)
            attention_mask = inputs['attention_mask'].to(device)
            embeddings = model(input_ids, attention_mask=attention_mask)
            outputs = embeddings.last_hidden_state[:, 0, :]
            outputs = F.normalize(outputs, p=2, dim=1)

            output = outputs.detach().cpu()

        elif model_name == "spladev2":
            input_ids = inputs['input_ids'].to(device)
            attention_mask = inputs['attention_mask'].to(device)
            embeddings = model(input_ids, attention_mask=attention_mask)
            outputs = (torch.sum(embeddings.last_hidden_state * attention_mask.unsqueeze(-1), dim=1) / \
                       torch.sum(attention_mask, dim=-1, keepdim=True))
            outputs = F.normalize(outputs, p=2, dim=1)

            output = outputs.detach().cpu()

    # this is the numpy array for the embedding of the batch
    return output.numpy()


def get_embedding_arguana(model_name, model, tokenizer, text, cuda="cpu", batch_size=30):
    """
    Input model: loaded model
          tokenizer: associated tokenizer
          text: a list of strings, each string is either a query or an abstract
          cuda: in the format of "0,1,6,7" or "0", by default, cpu option is used
          batch_size: if not specified, then an optimal batch_size is found by system, else,
                       the user specified batch_size is used, may run into OOM error.
    Return:  the embedding dictionary, where the key is a string (e.g. an abstract, query/subquery), and the value
             is np.ndarray of the vector, usually 1 or 2 dimensions.
    """
    if cuda != "cpu":
        if model_name in ["ot_aspire", "ts_aspire", "sentbert", "ance"]:
            cuda = cuda.split(",")[0]
        #             cuda = cuda[0] # aspire, sentbert, ance do not currently support multiple gpus.
        cuda_list = cuda.split(",")
        cuda_num = len(cuda_list)

        # batch_size = optimal_batch_size(model_name, model, tokenizer, text, cuda_num, cuda, batch_size)

        length = ceil(len(text) / batch_size)
    else:
        batch_size = 1

    ret = {}
    length = ceil(len(text) / batch_size)
    # for i in tqdm(range(length),desc='embedding: '):
    for i in (range(length)):
        curr_batch = text[i * batch_size:(i + 1) * batch_size]
        curr_batch_cleaned = [preprocessing(t) for t in curr_batch]
        inputs = tokenization(model_name, tokenizer, curr_batch_cleaned)
        embedding = encoding(model_name, model, inputs, cuda)
        for t, v in zip(curr_batch, embedding):
            ret[t] = v
    #         del inputs
    #         torch.cuda.empty_cache()

    # ret is a dictionary, keys are text, and values are their embeddings
    return ret





