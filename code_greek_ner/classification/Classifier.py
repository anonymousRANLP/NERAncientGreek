import numpy as np
from transformers import AutoTokenizer, AutoModelForTokenClassification, AutoConfig, TrainingArguments, Trainer, DataCollatorForTokenClassification, IntervalStrategy, EarlyStoppingCallback
from data.CONLLReader import CONLLReader
import torch
from argparse import ArgumentParser
import json
from tokenization import Tokenization
from data import Datasets
from datasets import load_metric
from sklearn.metrics import classification_report

class Classifier:
    
    def __init__(self,transformer_path,model_dir,tokenizer_path,training_data=None,eval_data=None,test_data=None,ignore_label=None,unknown_label=None,data_preset='CONLL',feature_cols=None, add_prefix_space=False, max_length=512):
        self.device = torch.device('cuda') if torch.cuda.is_available() else torch.device('cpu')
        if tokenizer_path is None:
            self.tokenizer = AutoTokenizer.from_pretrained(transformer_path, add_prefix_space=add_prefix_space, max_length=max_length)
        else:
            self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, add_prefix_space=add_prefix_space, max_length=max_length)
        self.prefix_subword_id = None
        if '▁' in self.tokenizer.vocab.keys():
            self.prefix_subword_id = self.tokenizer.convert_tokens_to_ids('▁')
        self.transformer_path = transformer_path
        self.model_dir = model_dir
        self.reader = CONLLReader(data_preset,feature_cols)
        if training_data is not None:
            self.training_data = self.reader.parse_conll(training_data)
        else:
            self.training_data = None
        if test_data is not None:
            self.test_data = self.reader.parse_conll(test_data)
        else:
            self.test_data = None
        if eval_data is not None:
            self.eval_data = self.reader.parse_conll(eval_data)
        else:
            self.eval_data = None
        self.ignore_label = ignore_label
        self.unknown_label = unknown_label

    
    def id_label_mappings(self,tags):
        unique_tags = set(tag for doc in tags for tag in doc)
        if self.ignore_label is not None:
            unique_tags.remove(self.ignore_label)
        tag2id = {tag: s_id for s_id, tag in enumerate(sorted(unique_tags))}
        id2tag = {s_id: tag for tag, s_id in tag2id.items()}
        return tag2id, id2tag
    
#     def get_valid_subwords(self, subword_ids, last_subword=True):
#         # Valid subwords is a list with None for the special tokens ([CLS], [SEP] etc.) and ids for each part of the respective word
#         # E.g.:
#         #[CLS] None
#         #ὁ 0
#         #γάρ 1
#         #κόσμο 2
#         #ς 2
#         #προϋ 3
#         #φέστηκε 3
#         #πάντων 4
#         #τελειότατο 5
#         #ς 5
#         #ὤν 6
#         #· 7
#         #[SEP] None
#         valid_subwords = []
#         for i, current_subword_id in enumerate(subword_ids):
#             if current_subword_id is None:
#                 # Any special token is not a valid subword
#                 valid_subwords.append(False)
#             elif last_subword:
#                 # If we want to label the last subword, we have the following cases
#                 # If the token is at the end of the list, and has a number, it is automatically a valid subword
#                 # Note, this would not happen unless we don't have a [SEP] token, but added just in case
#                 if i == len(subword_ids) - 1:
#                     valid_subwords.append(True)
#                 # If the next token has the same id as the current token, it is not the last subtoken and not a valid subword
#                 elif subword_ids[i+1] == current_subword_id:
#                     valid_subwords.append(False)
#                 # Otherwise, it is the last subtoken of the word
#                 else:
#                     valid_subwords.append(True)
#             else:
#                 # If we want to label the first subword, we have the following cases
#                 # If the token is at the start of the list, and has a number, it is automatically a valid subword
#                 # Note, this would not happen unless we don't have a [CLS] token, but added just in case
#                 if i==0:
#                     valid_subwords.append(True)
#                 # If the previous token has the same id as the current token, it is not the first subtoken and not a valid subword
#                 elif subword_ids[i-1] == current_subword_id:
#                     valid_subwords.append(False)
#                 # Otherwise, it is the first subtoken of the word
#                 else:
#                     valid_subwords.append(True)
#         return valid_subwords
    
#     def align_labels(self, sentence, tag2id, last_subword=True, prefix_subword_id=None, labelname='MISC', is_tensor=False):
#         labels = sentence[labelname]
#         offset = sentence['offset_mapping']
#         input_ids = sentence['input_ids']
        
#         if is_tensor:
#             offset = offset[0]
#             input_ids = input_ids[0]
        
#         valid_subwords = self.get_valid_subwords(input_ids,last_subword=last_subword)
        
#         enc_labels = np.ones(len(valid_subwords),dtype=int) * - 100
        
#         label_match_id = -1
        
#         for n_subword, valid_subword in enumerate(valid_subwords):
#             if valid_subword:
#                 label_match_id += 1
#                 label = labels[label_match_id]
#                 if not (self.ignore_label is not None and self.ignore_label==label):
#                     enc_labels[n_subword] = tag2id[label]
        
#         sentence['labels'] = enc_labels
#         return sentence
    def get_valid_subwords(self, subword_ids, last_subword=True):
        # subword_ids is a list with None for the special tokens ([CLS], [SEP] etc.) and ids for each part of the respective word
        # E.g.:
        #[CLS] None
        #ὁ 0
        #γάρ 1
        #κόσμο 2
        #ς 2
        #προϋ 3
        #φέστηκε 3
        #πάντων 4
        #τελειότατο 5
        #ς 5
        #ὤν 6
        #· 7
        #[SEP] None
        valid_subwords = []
        for i, current_subword_id in enumerate(subword_ids):
            if current_subword_id is None:
                # Any special token is not a valid subword
                valid_subwords.append(False)
            elif last_subword:
                # If we want to label the last subword, we have the following cases
                # If the token is at the end of the list, and has a number, it is automatically a valid subword
                # Note, this would not happen unless we don't have a [SEP] token, but added just in case
                if i == len(subword_ids) - 1:
                    valid_subwords.append(True)
                # If the next token has the same id as the current token, it is not the last subtoken and not a valid subword
                elif subword_ids[i+1] == current_subword_id:
                    valid_subwords.append(False)
                # Otherwise, it is the last subtoken of the word
                else:
                    valid_subwords.append(True)
            else:
                # If we want to label the first subword, we have the following cases
                # If the token is at the start of the list, and has a number, it is automatically a valid subword
                # Note, this would not happen unless we don't have a [CLS] token, but added just in case
                if i==0:
                    valid_subwords.append(True)
                # If the previous token has the same id as the current token, it is not the first subtoken and not a valid subword
                elif subword_ids[i-1] == current_subword_id:
                    valid_subwords.append(False)
                # Otherwise, it is the first subtoken of the word
                else:
                    valid_subwords.append(True)
        return valid_subwords
    
    def align_labels(self, sentence, tag2id, last_subword=True, labelname='MISC'):
        labels = sentence[labelname]
        
        valid_subwords = self.get_valid_subwords(sentence['subword_ids'],last_subword=last_subword)
        try:
            assert len([x for x in valid_subwords if x == True]) == len(sentence['tokens'])
        except AssertionError:
            print(sentence)
        
        enc_labels = np.ones(len(valid_subwords),dtype=int) * - 100
        
        label_match_id = -1
        
        for n_subword, valid_subword in enumerate(valid_subwords):
            if valid_subword:
                label_match_id += 1
                if label_match_id > (len(labels)-1):
                    print(sentence)
                    for subword_no, subword in enumerate(sentence['input_ids']):
                        print(self.tokenizer.decode(subword)+" "+str(sentence['offset_mapping'][subword_no]))
                label = labels[label_match_id]
                if not (self.ignore_label is not None and self.ignore_label==label):
                    enc_labels[n_subword] = tag2id[label]
        
        sentence['labels'] = enc_labels
        return sentence
    
    def align_token_type_ids(self, sentence):
        token_type_ids = sentence['token_type_ids']
        new_token_type_ids = []
        for subword_id in sentence['subword_ids']:
            if subword_id != None:
                new_token_type_ids.append(token_type_ids[subword_id])
            else:
                new_token_type_ids.append(0)
        
        sentence['token_type_original'] = token_type_ids
        sentence['token_type_ids'] = new_token_type_ids
        return sentence
    
#     def tokenize_and_align_labels(self, sentence, tag2id, last_subword=True, prefix_subword_id=None, labelname='MISC', is_tensor=False):
        
#         tokenizer = self.tokenizer

#         encodings = tokenizer(sentence['tokens'], truncation=True, max_length=514, is_split_into_words=True, return_offsets_mapping=True)
#         wids = encodings.word_ids()
        
#         labels = sentence[labelname]
#         # tokens = sentence['tokens']

#         if is_tensor:
#             offset = offset[0]
#             input_ids = input_ids[0]

#         # valid_subwords = get_valid_subwords(offset,input_ids,last_subword=last_subword,prefix_subword_id=prefix_subword_id, tokens=tokens)

#         # if last_subword

#         enc_labels = []

#         label_idx = 0

#         for index, wid in enumerate(wids):
#             if wid == None: #BOS and EOS tokens of the encoded sentence get wid None
#                 enc_labels.append(-100)
#             else:
#                 if last_subword == False:
#                     if wid != wids[index-1]:  # Only label the first token of a given word.
#                         if not (self.ignore_label is not None and self.ignore_label==labels[label_idx]):
#                             enc_labels.append(tag2id[labels[label_idx]])
#                         else:
#                             enc_labels.append(-100)
#                         label_idx = label_idx + 1
#                     else:
#                         enc_labels.append(-100)
#                 else:
#                     if wid != wids[index+1]: # Only label the last token of a given word.
#                         if not (self.ignore_label is not None and self.ignore_label==labels[label_idx]):
#                             enc_labels.append(tag2id[labels[label_idx]])
#                         else:
#                             enc_labels.append(-100)
#                         label_idx = label_idx + 1
#                     else:
#                         enc_labels.append(-100)

#         encodings['labels'] = enc_labels
#         return encodings
    
    def flatten_list(self, nested_list):
        flattened = []
        for sublist in nested_list:
            if isinstance(sublist, list):
                flattened.extend(flatten_list(sublist))
            else:
                flattened.append(sublist)
        return flattened
    
    
    def compute_metrics(self, p, metric='sklearn'):
        id2tag = self.config.id2label
        #added compute_metrics for evaluation during training
        predictions, labels = p
        #select predicted index with maximum logit for each token
        predictions = np.argmax(predictions, axis=2)
        # Remove ignored index (special tokens)
        true_predictions = [
          [id2tag[p] for (p, l) in zip(prediction, label) if l != -100]
          for prediction, label in zip(predictions, labels)
        ]


        true_labels = [
          [id2tag[l] for (p, l) in zip(prediction, label) if l != -100]
          for prediction, label in zip(predictions, labels)
        ]
        if metric == 'seqeval_ner':
            metric = load_metric('seqeval')
            results = metric.compute(predictions=true_predictions, references=true_labels)
            return {
              "precision": results["overall_precision"],
              "recall": results['overall_recall'],
              "f1": results["overall_f1"]
        }
        if metric == "sklearn":
            results = classification_report([element for innerList in true_labels for element in innerList], [element for innerList in true_predictions for element in innerList], output_dict=True)
            return {
              "precision": results['macro avg']["precision"],
              "recall": results['macro avg']["recall"],
              "f1": results['macro avg']["f1-score"]
        }
        
    def train_classifier(self,output_model,train_dataset, tag2id,id2tag,eval_dataset=None, 
                          epochs=3,batch_size=16,learning_rate=5e-5, training_args=None):
        
        data_collator = DataCollatorForTokenClassification(tokenizer=self.tokenizer)        
        self.config = AutoConfig.from_pretrained(self.transformer_path, num_labels=len(tag2id), id2label=id2tag, label2id=tag2id)
        self.classifier_model = AutoModelForTokenClassification.from_pretrained(self.transformer_path,config=self.config)
        
        if training_args == None:
            training_args = TrainingArguments(output_dir=output_model,num_train_epochs=epochs,per_device_train_batch_size=batch_size,learning_rate=learning_rate,save_strategy='no')
        else:
                            training_args = training_args
        if eval_dataset == None:
            trainer = Trainer(model=self.classifier_model,
                              args=training_args,
                              train_dataset=train_dataset,
                              tokenizer=self.tokenizer,
                              data_collator=data_collator)
        else:
            
            trainer = Trainer(model=self.classifier_model,
              args=training_args,
              train_dataset=train_dataset,
              eval_dataset=eval_dataset,
              compute_metrics=self.compute_metrics,
              tokenizer=self.tokenizer,
              data_collator=data_collator,
              callbacks = [EarlyStoppingCallback(early_stopping_patience=3)]
              )
        trainer.train()
#         trainer.model.save_pretrained(save_directory=trainer.args.output_dir)
            
    def predict(self,test_data,model_dir=None,batch_size=16,labelname='MISC', max_length=512):        
        ##Only works when padding is set to the right!!! See below
        self.classifier_model = AutoModelForTokenClassification.from_pretrained(model_dir)
        self.config = AutoConfig.from_pretrained(model_dir)
        id2tag = self.config.id2label
        tag2id = self.config.label2id
        
        if self.unknown_label is not None:
            tag2id[self.unknown_label] = 0
        
        test_data = test_data.map(self.align_labels,fn_kwargs={"tag2id":tag2id,"labelname":labelname})
        
        data_collator = DataCollatorForTokenClassification(tokenizer=self.tokenizer, max_length=max_length)
        training_args = TrainingArguments(output_dir=self.model_dir,per_device_eval_batch_size=batch_size)
        trainer = Trainer(model=self.classifier_model,args=training_args,tokenizer=self.tokenizer,data_collator=data_collator)
        
        predictions = trainer.predict(test_data)
        softmaxed_predictions = torch.nn.functional.softmax(torch.from_numpy(predictions.predictions),dim=-1).tolist()
        
        # This only works when padding is set to the right, since the padded predictions will be longer than valid_subword
        all_preds = []
        for sent_no, sent in enumerate(test_data):
            valid_subwords = self.get_valid_subwords(sent['subword_ids'])
            for subword_no, valid_subword in enumerate(valid_subwords):
                if valid_subword:
                    # If a (sub)word has the label defined by ignore_label, it is also set to -100 with classifier.align_labels, even though it is counted as a valid subword
                    if not ('labels' in sent and sent['labels'][subword_no] == -100):
                        preds = {}
                        for prob_n, prob in enumerate(softmaxed_predictions[sent_no][subword_no]):
                            classname = id2tag[prob_n]
                            preds[classname] = prob
                        all_preds.append(preds)
        
        return all_preds
        
    
    def write_prediction(self,wids,tokens,tags,preds,output_file,output_format,output_sentence=True):
        with open(output_file, 'w', encoding='UTF-8') as outfile:
            if output_format == 'tab':
                outfile.write("id\ttoken\tgold\tprediction\tprobability")
                if output_sentence:
                    outfile.write("\tsentence")
                outfile.write('\n')
            word_no = -1
            for sent_id, sent in enumerate(tokens):
                for word_id, word in enumerate(sent):
                    wid = wids[sent_id][word_id]
                    tag = tags[sent_id][word_id]
                    if self.ignore_label is not None and tag == self.ignore_label:
                        if output_format == 'CONLL':
                            outfile.write(wid + "\t" + word + "\t_\t_\t_\t_\t_\t_\t_\t_\n")
                        elif output_format == 'simple':
                            outfile.write(wid + "\t" + word + "\t_\n")
                    else:
                        word_no += 1
                        top_prediction = sorted(preds[word_no].items(), reverse=True, key=lambda x: x[1])[0]
                        if output_format == 'CONLL':
                            outfile.write(wid + "\t" + word + "\t_\t_\t_\t_\t_\t_\t_\t"+top_prediction[0]+"\n")
                        elif output_format == 'simple':
                            outfile.write(wid + "\t" + word + "\t"+top_prediction[0]+"\n")
                        elif output_format == 'tab':
                            outfile.write(wid + "\t" + word + "\t" + tag +"\t" + top_prediction[0] + "\t" + f"{top_prediction[1]:.5f}")
                            if output_sentence:
                                sent_str = ''
                                for word_id_2, word_2 in enumerate(sent):
                                    if word_id_2 == word_id:
                                        sent_str+='['
                                    sent_str+= word_2
                                    if word_id_2 == word_id:
                                        sent_str+=']'
                                    sent_str+= ' '
                                outfile.write('\t'+sent_str.strip())
                            outfile.write('\n')
                if output_format == 'CONLL' or output_format == 'simple':
                    outfile.write('\n')
                        
if __name__ == '__main__':
    arg_parser = ArgumentParser()
    arg_parser.add_argument('mode',help='train/test')
    arg_parser.add_argument('transformer_path',help='path to the transformer model')
    arg_parser.add_argument('model_dir',help='path of classifier model')
    arg_parser.add_argument('--tokenizer_path',help='path to the tokenizer (defaults to the path of the transformer model)')
    arg_parser.add_argument('--training_data',help='classifier training data')
    arg_parser.add_argument('--test_data',help='classifier test data')
    arg_parser.add_argument('--output_file',help='classified data')
    arg_parser.add_argument('--output_format',help='format of the output data: CONLL (standard CONLL, with prediction in MISC), simple (CONLL-style with only columns ID, FORM and MISC=prediction) or tab (tabular format, with prediction probabilities, no sentence boundaries and without irrelevant tokens)',default='CONLL')
    arg_parser.add_argument('--ignore_label',help='all tokens with this tag will be ignored during training or classification')
    arg_parser.add_argument('--unknown_label',help='tag in the test data for tokens for which we do not know the label beforehand')
    arg_parser.add_argument('--data_preset',help='format of the data, defaults to CONLL (other option: simple, where the data has columns ID, FORM, MISC)',default='CONLL')
    arg_parser.add_argument('--feature_cols',help='define a custom format for the data, e.g. {"ID":0,"FORM":2,"MISC":3}')
    arg_parser.add_argument('--normalization_rule',help='normalize tokens during training/testing, normalization rules implemented are greek_glaux and standard NFD/NFKD/NFC/NFKC')
    arg_parser.add_argument('--epochs',help='number of epochs for training, defaults to 3',type=int,default=3)
    arg_parser.add_argument('--batch_size',help='batch size for training/testing, defaults to 16',type=int,default=16)
    arg_parser.add_argument('--learning_rate',help='learning rate for training, defaults to 5e-5',type=float,default=5e-5)
    args = arg_parser.parse_args()
    feature_cols = args.feature_cols
    if feature_cols is not None:
        # Only required for Eclipse
        feature_cols = json.loads(feature_cols.replace('\'','"'))
        # Other
        # feature_cols = json.loads(feature_cols)
    if args.mode == 'train':
        if args.training_data == None:
            print('Training data is missing')
        else:
            classifier = Classifier(args.transformer_path,args.model_dir,args.tokenizer_path,args.training_data,args.test_data,args.ignore_label,args.unknown_label,args.data_preset,feature_cols)
            tokens, tags = classifier.reader.read_tags('MISC', classifier.training_data, in_feats=False,return_wids=False)
            tag_dict = {'MISC':tags}
            tokens_norm = tokens
            if args.normalization_rule is not None:
                tokens_norm = Tokenization.normalize_tokens(tokens, args.normalization_rule)
            tag2id, id2tag = classifier.id_label_mappings(tags)
            training_data = Datasets.build_dataset(tokens_norm,tag_dict)
            training_data = training_data.map(Tokenization.tokenize_sentence,fn_kwargs={"tokenizer":classifier.tokenizer})
            training_data = training_data.map(classifier.align_labels,fn_kwargs={"prefix_subword_id":classifier.prefix_subword_id,"tag2id":tag2id})
            classifier.train_classifier(classifier.model_dir,training_data,tag2id=tag2id,id2tag=id2tag,epochs=args.epochs,batch_size=args.batch_size,learning_rate=args.learning_rate)
    elif args.mode == 'test':
        if args.test_data == None:
            print('Test data is missing')
        else:
            classifier = Classifier(args.transformer_path,args.model_dir,args.tokenizer_path,args.training_data,args.test_data,args.ignore_label,args.unknown_label,args.data_preset,feature_cols)
            wids, tokens, tags = classifier.reader.read_tags('MISC', classifier.test_data, False)
            tags_dict = {'MISC':tags}
            tokens_norm = tokens
            if args.normalization_rule is not None:
                tokens_norm = Tokenization.normalize_tokens(tokens, args.normalization_rule)
            test_data = Datasets.build_dataset(tokens,tags_dict)
            test_data = test_data.map(Tokenization.tokenize_sentence,fn_kwargs={"tokenizer":classifier.tokenizer})
            prediction = classifier.predict(test_data,model_dir=classifier.model_dir,batch_size=args.batch_size)
            if args.output_file is not None:
                classifier.write_prediction(wids,tokens,tags,prediction,args.output_file,args.output_format)
                