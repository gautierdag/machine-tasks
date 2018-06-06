# -*- coding: utf-8 -*-
from __future__ import unicode_literals, division, absolute_import, print_function

import sys
import os
import itertools
import random
import operator
import warnings
import argparse
from functools import reduce

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split


### MAIN ###
def parse_arguments(args):
    parser = argparse.ArgumentParser(description="Script to generate of the lookup tables problem.",
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument('-d', '--dir', default='.', help='Path to the directory where to save the generated data.')
    parser.add_argument('-s', '--n-samples', type=int, default=1, help='Path to the directory where to save the generated data.')

    parser.add_argument('-v', '--validation-size', type=float, default=0.1, help='Percentage of training set to use as validation.')
    parser.add_argument('-c', '--max-composition-train', type=int, default=4, help='Max length of compositions in training set.')
    parser.add_argument('-t', '--n-unary-tables', type=int, default=8, help='Number of different lookup tables.')
    parser.add_argument('-T', '--n-heldout-tables', type=int, default=2, help='Number of tables that would only be seen in unary.')
    parser.add_argument('-C', '--n-heldout-compositions', type=int, default=50, help='Number of compositions to randomly remove.')
    parser.add_argument('-I', '--n-heldout-inputs', type=int, default=2, help='Number of inputs to heldout from training.')
    parser.add_argument('-l', '--n-longer', type=int, default=2, help='Number of additional tables to add to `longer` test data.')
    parser.add_argument('--not-intermediate', action='store_true', help='Removes intermediate step in the target sequence.')
    parser.add_argument('--not_shuffle', action='store_true', help='Disables shuffling of the outputed datasets')
    parser.add_argument('--not_reverse', action='store_true', help='Disables reversing of the input sequence. I.e if given, then uses `t1∘t2 input` instead of `input t2 t1`.')
    parser.add_argument('--not_stratify', action='store_true', help='Disables the balancing of the lookups in train and validation set.')
    parser.add_argument('-e', '--eos', default='.', help='EOS token to append at the end of each input.')
    parser.add_argument('-b', '--bound-longer', type=int, default=10**4, help='Bounds the maximum number of permuted compositions in `longer`')
    parser.add_argument('-a', '--alphabet', metavar=('letter1', 'letter2'), nargs='*', default=['0', '1'], help='Possible characters given as input.')
    parser.add_argument('-r', '--n-repeats', type=int, default=3, help='Number of characters in `alphabet` used in each input and output.')
    parser.add_argument('-S', '--seed', type=int, default=123, help='Random seed.')

    args = parser.parse_args(args)
    return args


def main(args):
    random.seed(args.seed)
    for sample in range(args.n_samples):
        seed = args.seed if args.n_samples == 1 else random.randint(0, 1e5)
        print(seed)
        out = table_lookup_dataset(validation_size=args.validation_size,
                                   max_composition_train=args.max_composition_train,
                                   n_unary_tables=args.n_unary_tables,
                                   n_heldout_tables=args.n_heldout_tables,
                                   n_heldout_compositions=args.n_heldout_compositions,
                                   n_heldout_inputs=args.n_heldout_inputs,
                                   add_composition_test=args.n_longer,
                                   is_intermediate=not args.not_intermediate,
                                   is_shuffle=not args.not_shuffle,
                                   is_reverse=not args.not_reverse,
                                   is_stratify=not args.not_stratify,
                                   eos=args.eos,
                                   max_longer=args.bound_longer,
                                   seed=seed,
                                   alphabet=args.alphabet,
                                   n_repeats=args.n_repeats)

        names = ("train", "validation", "heldout_inputs", "heldout_compositions", "heldout_tables",
                 "new_compositions", "longer_seen", "longer_incremental", "longer_new")

        for data, name in zip(out, names):
            path = args.dir if args.n_samples == 1 else os.path.join(args.dir, "sample{}".format(sample + 1))
            _save_tsv(data, name, path)


### FUNCTIONS ###
def table_lookup_dataset(validation_size=0.11,
                         max_composition_train=2,
                         n_unary_tables=8,
                         n_heldout_tables=2,
                         n_heldout_compositions=8,
                         n_heldout_inputs=2,
                         add_composition_test=1,
                         is_intermediate=True,
                         is_shuffle=True,
                         is_reverse=True,
                         is_stratify=True,
                         eos=".",
                         max_longer=10**4,
                         seed=123,
                         **kwargs):
    r"""Prepare the table lookup dataset.

    Args:
        validation_size (float, optional): max length of compositions in training set.
        max_composition_train (int, optional): max length of compositions in training set.
        n_unary_tables (int, optional): number of different lookup tables.
        n_heldout_tables (int, optional): number of tables that would only be seen in unary.
        n_heldout_compositions (int, optional): number of compositions to randomly remove.
        n_heldout_inputs (int, optional): the number of inputs to heldout from training.
        add_composition_test (int, optional): additional composition to add for the `longer_*` test data.
            Those test sets will then include compositions between `max_composition_train` and
            `max_composition_train + add_composition_test` tables.
        is_intermediate (bool, optional): whether to include intermediate results in the output.
        is_shuffle (bool, optional): whether to shuffle the outputed datasets.
        is_reverse (bool, optional): whether to have the inputs first and then the tables. Ex: if reverse:
            001 t1 t2 else t2 t1 001.
        is_stratify (bool, optional): whether to split validation to approximately balance each lookup table.
            `validation_size` may have to be larger when using this.
        eos (str, optional): str to append at the end of each input.
        max_longer (int, optional): bounds the maximum number of rows in `longer`.
        seed (int, optional): sets the seed for generating random numbers.
        kwargs: Additional arguments to `create_N_table_lookup`.

    Returns:
        train (pd.Series): dataframe of all multiary training examples. Contains all the unary functions.
            The index is the input and value is the target.
        validation (pd.Series): dataframe of all multiary examples use for validation.
        heldout_inputs (pd.Series): dataframe of inputs that have not been seen during training but the mapping have.
        heldout_compositions (pd.Series): dataframe of multiary composition that have never been seen during training.
        heldout_tables (pd.Series): dataframe of multiary composition that are made up of one table that has
            never been seen in any multiary composition during training.
        new_compositions (pd.Series): dataframe of multiary composition that are made up of 2 tables that have
            never been seen in any multiary composition during training.
        longer_seens (list of pd.Series): list of len `add_composition_test`. Where the ith element is a dataframe
            composed of `max_composition_train+i` tables that have all been composed in the training set.
        longer_incrementals (list of pd.Series): list of len `add_composition_test`. Where the ith element is a
            dataframe composed of `max_composition_train+i` tables, with at least one that been composed in the
            training set and at least one that hasn't.
        longer_news (list of pd.Series): ist of len `add_composition_test`. Where the ith element is a
            dataframe composed of `max_composition_train+i` tables that have never been composed in the training set.
    """
    np.random.seed(seed)
    random.seed(seed)

    unary_functions = create_N_table_lookup(N=n_unary_tables, seed=seed, **kwargs)
    names_unary_train = {t.name for t in unary_functions[:-n_heldout_tables]}
    names_unary_test = {t.name for t in unary_functions[-n_heldout_tables:]}
    multiary_functions = flatten([[reduce(lambda x, y: compose_table_lookups(x, y, is_intermediate=is_intermediate),
                                          fs)
                                   for fs in itertools.product(unary_functions, repeat=repeat)]
                                  for repeat in range(2, max_composition_train + 1)])
    multiary_train, heldout_tables, new_compositions = _split_seen_unseen_new(multiary_functions,
                                                                              names_unary_train,
                                                                              names_unary_test)
    random.shuffle(multiary_train)

    # heldout
    heldout_compositions = multiary_train[-n_heldout_compositions:]

    multiary_train = multiary_train[:-n_heldout_compositions]
    drop_inputs = [np.random.choice(table.index, n_heldout_inputs, replace=False)
                   for table in multiary_train]
    heldout_inputs = [table[held_inputs] for held_inputs, table in zip(drop_inputs, multiary_train)]

    multiary_train = [table.drop(held_inputs) for held_inputs, table in zip(drop_inputs, multiary_train)]

    # longer
    longer_seens = []
    longer_incrementals = []
    longer_news = []
    longest_multiary_functions = [t for t in multiary_functions if len(t.name.split()) == max_composition_train]
    longer = [compose_table_lookups(x, y) for x, y in itertools.product(unary_functions, longest_multiary_functions)]
    for _ in range(add_composition_test):
        if len(longer) > max_longer:
            warnings.warn("Randomly select tables as len(longer)={} is larger than max_longer={}.".format(len(longer), max_longer))
            longer = random.sample(longer, max_longer)

        longer_seen, longer_incremental, longer_new = _split_seen_unseen_new(longer,
                                                                             names_unary_train,
                                                                             names_unary_test)
        longer_seens.append(longer_seen)
        longer_incrementals.append(longer_incremental)
        longer_news.append(longer_new)
        longer = [compose_table_lookups(x, y) for x, y in itertools.product(unary_functions, longer)]

    # formats
    longer_seens = _merge_format_inputs(longer_seens, is_shuffle, seed=seed, is_reverse=is_reverse, eos=eos)
    longer_incrementals = _merge_format_inputs(longer_incrementals, is_shuffle, seed=seed, is_reverse=is_reverse, eos=eos)
    longer_news = _merge_format_inputs(longer_news, is_shuffle, seed=seed, is_reverse=is_reverse, eos=eos)

    building_blocks = (unary_functions, multiary_train, heldout_inputs, heldout_compositions, heldout_tables, new_compositions)
    building_blocks = _merge_format_inputs(building_blocks, is_shuffle, seed=seed, is_reverse=is_reverse, eos=eos)
    _check_sizes(building_blocks, max_composition_train, n_unary_tables, n_heldout_tables, n_heldout_compositions, n_heldout_inputs)
    unary_functions, multiary_train, heldout_inputs, heldout_compositions, heldout_tables, new_compositions = building_blocks

    # validation
    multiary_train, validation = _uniform_split(multiary_train, names_unary_train, validation_size=validation_size, seed=seed)
    train = pd.concat([unary_functions, multiary_train], axis=0)

    return (train,
            validation,
            heldout_inputs,
            heldout_compositions,
            heldout_tables,
            new_compositions,
            longer_seens,
            longer_incrementals,
            longer_news)


def create_N_table_lookup(N=None,
                          alphabet=['0', '1'],
                          n_repeats=3,
                          namer=lambda i: "t{}".format(i + 1),
                          seed=123):
    """Create N possible table lookups.

    Args:
        N (int, optional): number of tables lookups to create. (default: all posible)
        alphabet (list of char, optional): possible characters given as input.
        n_repeats (int, optional): number of characters in `alphabet` used in each input and output.
        namer (callable, optional): function that names a table given an index.
        seed (int, optional): sets the seed for generating random numbers.

    Returns:
        out (list of pd.Series): list of N dataframe with keys->input, data->output, name->namer(i).
    """
    np.random.seed(seed)
    inputs = np.array(list(''.join(letters)
                           for letters in itertools.product(alphabet, repeat=n_repeats)))
    iter_outputs = itertools.permutations(inputs)
    if N is not None:
        iter_outputs = np.array(list(iter_outputs))
        indices = np.random.choice(range(len(iter_outputs)), size=N, replace=False)
        iter_outputs = iter_outputs[indices]
    return [pd.Series(data=outputs, index=inputs, name=namer(i)) for i, outputs in enumerate(iter_outputs)]


def compose_table_lookups(table1, table2, is_intermediate=True):
    """Create a new table lookup as table1 ∘ table2."""
    left = table1.to_frame()
    right = table2.to_frame()
    right['next_input'] = right.iloc[:, 0].str.split().str[-1]
    merged_df = pd.merge(left, right, left_index=True, right_on='next_input').drop("next_input", axis=1)
    left_col, right_col = merged_df.columns

    if is_intermediate:
        merged_serie = merged_df[right_col] + " " + merged_df[left_col]
    else:
        merged_serie = merged_df[left_col]

    merged_serie.name = " ".join([left_col.split("_")[0], right_col.split("_")[0]])

    return merged_serie


def format_input(table, is_reverse=True, eos=None):
    """Formats the input of the task.

    Args:
        table (pd.Series, optional): Serie where keys->input, data->output, name->namer(i)
        is_reverse (bool, optional): whether to have the inputs first and then the tables. Ex: if reverse:
            001 t1 t2 else t2 t1 001.
        eos (str, optional): str to append at the end of each input.

    Returns:
        out (pd.Series): Serie where keys->input+name, data->output, name->namer(i).
    """
    table.index = ["{} {}".format(table.name, i) for i in table.index]

    if is_reverse:
        table.index = [" ".join(i.split()[::-1]) for i in table.index]

    if eos is not None and eos != "":
        table.index = ["{} {}".format(i, eos) for i in table.index]

    return table


### HELPERS ###
def _save_tsv(data, name, path):
    try:
        os.makedirs(path)
    except OSError:
        if not os.path.isdir(path):
            raise

    if isinstance(data, list):
        for i, df in enumerate(data):
            df.to_csv(os.path.join(path, "{}_{}.tsv".format(name, i + 1)), sep=str('\t'))  # wraps sep around str for python 2
    else:
        data.to_csv(os.path.join(path, "{}.tsv".format(name)), sep=str('\t'))  # wraps sep around str for python 2


def flatten(l):
    if isinstance(l, list):
        return reduce(operator.add, l)
    else:
        return l


def assert_equal(a, b):
    assert a == b, "{} != {}".format(a, b)


def _split_seen_unseen_new(dfs, name_train, name_test):
    """Split list of datatframes such that `seen` has only tables in `name_train`, `new` has only tables
    in `name_test`, and the rest is in `unseen`."""

    def _table_is_composed_of(composed_table, tables):
        return set(composed_table.name.split()).intersection(tables)

    seen = [t for t in dfs if not _table_is_composed_of(t, name_test)]
    new = [t for t in dfs if not _table_is_composed_of(t, name_train)]
    unseen = [t for t in dfs if _table_is_composed_of(t, name_test) and _table_is_composed_of(t, name_train)]
    return seen, unseen, new


def _merge_format_inputs(list_dfs, is_shuffle, seed=None, **kwargs):
    list_df = [pd.concat([format_input(df, **kwargs) for df in dfs],
                         axis=0)
               for dfs in list_dfs]

    if is_shuffle:
        list_df = [df.sample(frac=1, random_state=seed) for df in list_df]

    return list_df


def _uniform_split(to_split, table_names, validation_size=0.1, seed=None, is_stratify=True):
    df = to_split.to_frame()
    for name in table_names:
        df[name] = [name in i.split() for i in df.index]
    df['length'] = [len(i.split()) for i in df.index]

    stratify = df.iloc[:, 1:] if is_stratify else None

    try:
        train, test = train_test_split(to_split, test_size=validation_size, random_state=seed, stratify=stratify)
    except ValueError:
        warnings.warn("Doesn't use stratfy as given validation_size was to small.")
        train, test = train_test_split(to_split, test_size=validation_size, random_state=seed, stratify=None)

    return train, test


def _check_sizes(dfs, max_length, n_unary_tables, n_heldout_tables, n_heldout_compositions, n_heldout_inputs):
    unary_functions, multiary_train, heldout_inputs, heldout_compositions, heldout_tables, new_compositions = dfs

    n_repeats = len(unary_functions.iloc[0])
    alphabet = len(set("".join(unary_functions)))

    n_inputs = alphabet**n_repeats
    n_train_tables = n_unary_tables - n_heldout_tables
    n_train_compositions = sum(n_train_tables**i for i in range(2, max_length + 1)) - n_heldout_compositions

    def _size_permute_compose(n_tables):
        return sum(n_tables**i * n_inputs for i in range(2, max_length + 1))

    assert_equal(len(unary_functions), n_unary_tables * n_inputs)
    assert_equal(len(multiary_train), n_train_compositions * (n_inputs - n_heldout_inputs))
    assert_equal(len(heldout_inputs), n_train_compositions * n_heldout_inputs)
    assert_equal(len(heldout_compositions), n_heldout_compositions * n_inputs)
    assert_equal(len(heldout_tables), _size_permute_compose(n_train_tables + n_heldout_tables) -
                 _size_permute_compose(n_train_tables) -
                 _size_permute_compose(n_heldout_tables))
    assert_equal(len(new_compositions), _size_permute_compose(n_heldout_tables))


### SCRIPT ###
if __name__ == '__main__':
    args = parse_arguments(sys.argv[1:])
    main(args)
