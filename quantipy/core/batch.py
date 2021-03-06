#!/usr/bin/python
# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd
import quantipy as qp

from collections import OrderedDict

from quantipy.core.tools.qp_decorators import *

import copy as org_copy
import warnings
import re

from quantipy.core.tools.view.logic import (
    has_any, has_all, has_count,
    not_any, not_all, not_count,
    is_lt, is_ne, is_gt,
    is_le, is_eq, is_ge,
    union, intersection)

def meta_editor(self, dataset_func):
    """
    Decorator for inherited DataSet methods.
    """
    def edit(*args, **kwargs):
        # get name and type of the variable dor correct dict refernces
        name = args[0] if args else kwargs['name']
        if not isinstance(name, list): name = [name]
        # create DataSet clone to leave global meta data untouched
        ds_clone = self.clone()
        var_edits = []
        for n in name:
            is_array = self._is_array(n)
            is_array_item = self._is_array_item(n)
            has_edits = n in self.meta_edits
            parent = self._maskname_from_item(n) if is_array_item else None
            parent_edits = parent in self.meta_edits
            source = self.sources(n) if is_array else []
            source_edits = [s in self.meta_edits for s in source]
            # are we adding to aleady existing batch meta edits? (use copy then!)
            var_edits += [(n, has_edits), (parent, parent_edits)]
            var_edits += [(s, s_edit) for s, s_edit in zip(source, source_edits)]
        for var, edits in var_edits:
            if edits:
                copied_meta = org_copy.deepcopy(self.meta_edits[var])
                if not self._is_array(var):
                    ds_clone._meta['columns'][var] = copied_meta
                else:
                    ds_clone._meta['masks'][var] = copied_meta
                if self.meta_edits['lib'].get(var):
                    lib = self.meta_edits['lib'][var]
                    ds_clone._meta['lib']['values'][var] = lib
        # use qp.DataSet method to apply the edit
        dataset_func(ds_clone, *args, **kwargs)
        # grab edited meta data and collect via Batch.meta_edits attribute
        for n in name:
            if not self._is_array(n):
                meta = ds_clone._meta['columns'][n]
                text_edits = ['set_col_text_edit', 'set_val_text_edit']
                if dataset_func.func_name in text_edits and is_array_item:
                    self.meta_edits[parent] = ds_clone._meta['masks'][parent]
                    lib = ds_clone._meta['lib']['values'][parent]
                    self.meta_edits['lib'][parent] = lib
            else:
                meta = ds_clone._meta['masks'][n]
                if ds_clone._has_categorical_data(n):
                    self.meta_edits['lib'][n] = ds_clone._meta['lib']['values'][n]
            self.meta_edits[n] = meta
    return edit

def not_implemented(dataset_func):
    """
    Decorator for UNALLOWED DataSet methods.
    """
    def _unallowed_inherited_method(*args, **kwargs):
        err_msg = 'DataSet method not allowed for Batch editing!'
        raise NotImplementedError(err_msg)
    return _unallowed_inherited_method


class Batch(qp.DataSet):
    """
    A Batch is a container for structuring a Link collection's
    specifications aimed at Excel and/or PPTX build Clusters.
    """
    def __init__(self, dataset, name, ci=['c', 'p'], weights=None, tests=None):
        if '-' in name: raise ValueError("Batch 'name' must not contain '-'!")
        sets = dataset._meta['sets']
        if not 'batches' in sets: sets['batches'] = OrderedDict()
        self.name = name
        meta, data = dataset.split()
        self._meta = meta
        self._data = data.copy()
        self.valid_tks = dataset.valid_tks
        self.text_key = dataset.text_key
        self.sample_size = None
        self._verbose_errors = dataset._verbose_errors
        self._verbose_infos = dataset._verbose_infos

        if sets['batches'].get(name):
            if self._verbose_infos:
                print "Load Batch '{}'.".format(name)
            self._load_batch()
        else:
            sets['batches'][name] = {'name': name, 'additions': []}
            self.xks = []
            self.yks = ['@']
            self.extended_yks_global = None
            self.extended_yks_per_x = {}
            self.exclusive_yks_per_x = {}
            self.extended_filters_per_x = {}
            self.filter = 'no_filter'
            self.filter_names = ['no_filter']
            self.x_y_map = None
            self.x_filter_map = None
            self.y_on_y = None
            self.forced_names = {}
            self.summaries = []
            self.transposed_arrays = {}
            self.verbatims = OrderedDict()
            self.verbatim_names = []
            self.set_cell_items(ci)   # self.cell_items
            self.set_weights(weights) # self.weights
            self.set_sigtests(tests)  # self.siglevels
            self.additional = False
            self.meta_edits = {'lib': {}}
            self.set_language(dataset.text_key) # self.language
            self._update()

        # DECORATED / OVERWRITTEN DataSet methods
        self.hiding = meta_editor(self, qp.DataSet.hiding.__func__)
        self.sorting = meta_editor(self, qp.DataSet.sorting.__func__)
        self.slicing = meta_editor(self, qp.DataSet.slicing.__func__)
        self.set_variable_text = meta_editor(self, qp.DataSet.set_variable_text.__func__)
        self.set_value_texts = meta_editor(self, qp.DataSet.set_value_texts.__func__)
        self.set_property = meta_editor(self, qp.DataSet.set_property.__func__)
        # RENAMED DataSet methods
        self._dsfilter = qp.DataSet.filter.__func__
        # UNALLOWED DataSet methods
        self.add_meta = not_implemented(qp.DataSet.add_meta.__func__)
        self.derive = not_implemented(qp.DataSet.derive.__func__)
        self.remove_items = not_implemented(qp.DataSet.remove_items.__func__)


    def _update(self):
        """
        Update Batch metadata with Batch attributes.
        """
        self._map_x_to_y()
        self._map_x_to_filter()
        self._samplesize_from_batch_filter()
        for attr in ['xks', 'yks', 'filter', 'filter_names',
                     'x_y_map', 'x_filter_map', 'y_on_y',
                     'forced_names', 'summaries', 'transposed_arrays', 'verbatims',
                     'verbatim_names', 'extended_yks_global', 'extended_yks_per_x',
                     'exclusive_yks_per_x', 'extended_filters_per_x', 'meta_edits',
                     'cell_items', 'weights', 'siglevels', 'additional',
                     'sample_size', 'language', 'name']:
            attr_update = {attr: self.__dict__.get(attr)}
            self._meta['sets']['batches'][self.name].update(attr_update)

    def _load_batch(self):
        """
        Fill batch attributes with information from meta.
        """
        for attr in ['xks', 'yks', 'filter', 'filter_names',
                     'x_y_map', 'x_filter_map', 'y_on_y',
                     'forced_names', 'summaries', 'transposed_arrays', 'verbatims',
                     'verbatim_names', 'extended_yks_global', 'extended_yks_per_x',
                     'exclusive_yks_per_x', 'extended_filters_per_x', 'meta_edits',
                     'cell_items', 'weights', 'siglevels', 'additional',
                     'sample_size', 'language']:
            attr_load = {attr: self._meta['sets']['batches'][self.name].get(attr)}
            self.__dict__.update(attr_load)

    def copy(self, name):
        """
        Create a copy of Batch instance.

        Parameters
        ----------
        name: str
            Name of the Batch instance that is copied.

        Returns
        -------
        New/ copied Batch instance.
        """
        org_name = self.name
        org_meta = org_copy.deepcopy(self._meta['sets']['batches'][org_name])
        batch_copy = org_copy.deepcopy(self)
        self._meta['sets']['batches'][name] = org_meta
        batch_copy._meta['sets']['batches'][name] = org_meta
        batch_copy.name = name
        if batch_copy.verbatims:
            batch_copy.verbatims = {}
            batch_copy.verbatim_names = []
            if self._verbose_errors:
                warning = ("Copied Batch '{}' contains open end data summaries...\n"
                           "Any filters added to the copy will not persist "
                           "on verbatims so they have been removed! "
                           "Please add them again!")
                warnings.warn(warning.format(name))
        batch_copy._update()
        return batch_copy

    @modify(to_list='ci')
    def set_cell_items(self, ci):
        """
        Assign cell items ('c', 'p', 'cp').

        Parameters
        ----------
        ci: str/ list of str, {'c', 'p', 'cp'}
            Cell items used for this Batch instance.

        Returns
        -------
        None
        """
        if ci not in [['c'], ['p'], ['c', 'p'], ['p', 'c'], ['cp']]:
            raise ValueError("'ci' cell items must be either 'c', 'p' or 'cp'.")
        self.cell_items = ci
        self._update()
        return None

    @modify(to_list='w')
    def set_weights(self, w):
        """
        Assign a weight variable setup.

        Parameters
        ----------
        w: str/ list of str
            Name(s) of the weight variable(s).

        Returns
        -------
        None
        """
        if not w: w = [None]
        self.weights = w
        if any(weight not in self.columns() for weight in w if not weight is None):
            raise ValueError('{} is not in DataSet.'.format(w))
        self._update()
        return None

    @modify(to_list='levels')
    def set_sigtests(self, levels=None, mimic=None, flags=None, test_total=None):
        """
        Specify a significance test setup.

        Parameters
        ----------
        levels: float/ list of float
            Level(s) for significance calculation(s).
        mimic/ flags/ test_total:
            Currently not implemented.

        Returns
        -------
        None
        """
        if levels:
            if not all(isinstance(l, float) for l in levels):
                raise TypeError('All significance levels must be provided as floats!')
            levels = sorted(levels)
            self.siglevels = levels
        else:
            self.siglevels = []
        if mimic or flags or test_total:
            err = ("Changes to 'mimic', 'flags', 'test_total' currently not allowed!")
            raise NotImplementedError(err)
        self._update()
        return None

    @verify(text_keys='text_key')
    def set_language(self, text_key):
        """
        Set ``Batch.language`` indicated via the ``text_key`` for Build exports.

        Parameters
        ----------
        text_key: str
            The text_key used as language for the Batch instance

        Returns
        -------
        None
        """
        self.language = text_key
        self._update()
        return None

    def as_addition(self, batch_name):
        """
        Treat the Batch as additional aggregations, independent from the
        global Batch & Build setup.

        Parameters
        ----------
        batch_name: str
            Name of the Batch instance where the current instance is added to.

        Returns
        -------
        None
        """
        self._meta['sets']['batches'][batch_name]['additions'].append(self.name)
        self.additional = True
        self.verbatims = {}
        self.verbatim_names = []
        self.y_on_y = None
        if self._verbose_infos:
            msg = ("Batch '{}' specified as addition to Batch '{}'. Any open end "
                   "summaries and 'y_on_y' agg. have been removed!")
            print msg.format(self.name, batch_name)
        self._update()
        return None

    @modify(to_list='xks')
    def add_x(self, xks):
        """
        Set the x (downbreak) variables of the Batch.

        Parameters
        ----------
        xks: str, list of str, dict, list of dict
            Names of variables that are used as downbreaks. Forced names for
            Excel outputs can be given in a dict, for example:
            xks = ['q1', {'q2': 'forced name for q2'}, 'q3', ....]

        Returns
        -------
        None
        """
        clean_xks = self._check_forced_names(xks)
        self.xks = self.unroll(clean_xks, both='all')
        self._update()
        masks = [x for x in self.xks if x in self.masks()]
        self.make_summaries(masks)
        return None

    @modify(to_list='arrays')
    @verify(variables={'arrays': 'masks'})
    def make_summaries(self, arrays):
        """
        Summary tables are created for defined arrays.

        Parameters
        ----------
        arrays: str/ list of str
            List of arrays for which summary tables are created. Summary tables
            can only be created for arrays that are included in ``self.xks``.

        Returns
        -------
        None
        """
        if any(a not in self.xks for a in arrays):
            msg = '{} not defined as xks.'.format([a for a in arrays if not a in self.xks])
            raise ValueError(msg)
        self.summaries = arrays
        if arrays:
            msg = 'Array summaries setup: Creating {}.'.format(arrays)
        else:
            msg = 'Array summaries setup: Creating no summaries!'
        if self._verbose_infos:
            print msg
        for t_array in self.transposed_arrays.keys():
            if not t_array in arrays:
                self.transposed_arrays.pop(t_array)
        self._update()
        return None

    @modify(to_list='arrays')
    @verify(variables={'arrays': 'masks'})
    def transpose_arrays(self, arrays, replace=True):
        """
        Transposed summary tables are created for defined arrays.

        Parameters
        ----------
        arrays: str/ list of str
            List of arrays for which transposed summary tables are created.
            Transposed summary tables can only be created for arrays that are
            included in ``self.xks``.
        replace: bool, default True
            If True only the transposed table is created, if False transposed
            and normal summary tables are created.

        Returns
        -------
        None
        """
        if any(a not in self.xks for a in arrays):
            msg = '{} not defined as xks.'.format([a for a in arrays if not a in self.xks])
            raise ValueError(msg)
        if any(a not in self.summaries for a in arrays):
            ar = list(set(self.summaries + arrays))
            a = [v for v in self.xks if v in ar]
            self.make_summaries(a)
        for array in arrays:
            self.transposed_arrays[array] = replace
        self._update()
        return None

    @modify(to_list='yks')
    @verify(variables={'yks': 'both'}, categorical='yks')
    def add_y(self, yks):
        """
        Set the y (crossbreak/banner) variables of the Batch.

        Parameters
        ----------
        yks: str, list of str
            Variables that are added as crossbreaks. '@'/ total is added
            automatically.

        Returns
        -------
        None
        """
        yks = [y for y in yks if not y=='@']
        yks = self.unroll(yks)
        yks = ['@'] + yks
        self.yks = yks
        self._update()
        return None

    def add_x_per_y(self, x_on_y_map):
        """
        Add individual combinations of x and y variables to the Batch.

        !!! Currently not implemented !!!
        """
        raise NotImplemetedError('NOT YET SUPPPORTED')
        if not isinstance(x_on_y_map, list): x_on_y_maps = [x_on_y_map]
        if not isinstance(x_on_y_maps[0], dict):
            raise TypeError('Must pass a (list of) dicts!')
        for x_on_y_map in x_on_y_maps:
            for x, y in x_on_y_map.items():
                if not isinstance(y, list): y = [y]
                if isinstance(x, tuple): x = {x[0]: x[1]}
        return None

    def add_filter(self, filter_name, filter_logic):
        """
        Apply a (global) filter to all the variables found in the Batch.

        Parameters
        ----------
        filter_name: str
            Name for the added filter.
        filter_logic: complex logic
            Logic for the added filter.

        Returns
        -------
        None
        """
        self.filter = {filter_name: filter_logic}
        if filter_name not in self.filter_names:
            self.filter_names = [filter_name]
        self._update()
        return None

    @modify(to_list=['oe', 'break_by', 'title'])
    @verify(variables={'oe': 'columns', 'break_by': 'columns'})
    def add_open_ends(self, oe, break_by=None, drop_empty=True, incl_nan=False,
                      replacements=None, split=False, title='open ends',
                      filter_by=None):
        """
        Create respondent level based listings of open-ended text data.

        Parameters
        ----------
        oe : str or list of str
            The open-ended questions / verbatims to be added to the stack.
        break_by : str or list of str, default None
            If provided, these variables will be presented alongside the ``oe``
            data.
        drop_empty : bool, default True
            Case data that is missing valid entries will be dropped from the
            output.
        incl_nan: bool, default False
            Show __NaN__ in the output.
        replacements: dict, default None
            Replace strings in data.
        split: bool, default False
            If True len of oe must be same size as len of title. Each oe is
            saved with its own title.
        title : str, default 'open ends'
            Specifies the the ``Cluster`` / Excel sheet name for the output.
        filter_by : A Quantipy logical expression, default None
            An additional logical filter that should be applied to the case data.
            Any ``filter`` provided by a ``batch`` will be respected
            automatically.

        Returns
        -------
        None
        """
        def _add_oe(oe, break_by, title, drop_empty, incl_nan, filter_by):
            columns = break_by + oe
            oe_data = self._data.copy()
            if self.filter != 'no_filter':
                ds = qp.DataSet('open_ends')
                ds.from_components(oe_data, self._meta)
                slicer = ds.take(self.filter.values()[0])
                oe_data = oe_data.loc[slicer, :]
            if filter_by:
                ds = qp.DataSet('open_ends')
                ds.from_components(oe_data, self._meta)
                slicer = ds.take(filter_by)
                oe_data = oe_data.loc[slicer, :]
            oe_data = oe_data[columns]
            oe_data.replace('__NA__', np.NaN, inplace=True)
            if replacements:
                for target, repl in replacements.items():
                    oe_data.replace(target, repl, inplace=True)
            if drop_empty:
                oe_data.dropna(subset=oe, how='all', inplace=True)
            if not incl_nan:
                for col in oe:
                    oe_data[col].replace(np.NaN, '', inplace=True)
            self.verbatims[title] = oe_data
            self.verbatim_names.extend(oe)

        if split:
            if not len(oe) == len(title):
                msg = "Cannot derive verbatim DataFrame 'title' with more than 1 'oe'"
                raise ValueError(msg)
            for t, open_end in zip(title, oe):
                open_end = [open_end]
                _add_oe(open_end, break_by, t, drop_empty, incl_nan, filter_by)
        else:
            _add_oe(oe, break_by, title[0], drop_empty, incl_nan, filter_by)
        self._update()
        return None

    @modify(to_list=['ext_yks', 'on'])
    @verify(variables={'ext_yks': 'both', 'on': 'both'})
    def extend_y(self, ext_yks, on=None):
        """
        Add y (crossbreak/banner) variables to specific x (downbreak) variables.

        Parameters
        ----------
        ext_yks: str/ list of str
            Name(s) of variable(s) that are added as crossbreak.
        on: str/ list of str
            Name(s) of variable(s) in the xks (downbreaks) for which the
            crossbreak should be extended.

        Returns
        -------
        None
        """
        if not on:
            self.yks.extend(ext_yks)
            if not self.extended_yks_global:
                self.extended_yks_global = ext_yks
            else:
                self.extended_yks_global.extend(ext_yks)
        else:
            if any(o not in self.xks for o in on):
                msg = '{} not defined as xks.'.format([o for o in on if not o in self.xks])
                raise ValueError(msg)
            on = self.unroll(on, both='all')
            for x in on:
                self.extended_yks_per_x.update({x: ext_yks})
        self._update()
        return None

    @modify(to_list=['new_yks', 'on'])
    @verify(variables={'new_yks': 'both', 'on': 'both'})
    def replace_y(self, new_yks, on):
        """
        Replace y (crossbreak/banner) variables on specific x (downbreak) variables.

        Parameters
        ----------
        ext_yks: str/ list of str
            Name(s) of variable(s) that are used as crossbreak.
        on: str/ list of str
            Name(s) of variable(s) in the xks (downbreaks) for which the
            crossbreak should be replaced.

        Returns
        -------
        None
        """
        if any(o not in self.xks for o in on):
            msg = '{} not defined as xks.'.format([o for o in on if not o in self.xks])
            raise ValueError(msg)
        on = self.unroll(on, both='all')
        for x in on:
            self.exclusive_yks_per_x.update({x: new_yks})
        self._update()
        return None

    def extend_filter(self, ext_filters):
        """
        Apply additonal filtering to specific x (downbreak) variables.

        Parameters
        ----------
        ext_filters: dict
            dict with variable name(s) as key, str or tupel of str, and logic
            as value. For example:
            ext_filters = {'q1': {'gender': 1}, ('q2', 'q3'): {'gender': 2}}

        Returns
        -------
        None
        """
        for variables, logic in ext_filters.items():
            if not isinstance(variables, tuple) or len(variables) == 1:
                variables = [variables]
            for v in variables:
                new_filter = self._combine_filters({v: logic})
                if not new_filter.keys()[0] in self.filter_names:
                    self.filter_names.append(new_filter.keys()[0])
                self.extended_filters_per_x.update({v: new_filter})
                if self._is_array(v):
                    for s in self.sources(v):
                        new_filter = self._combine_filters({s: logic})
                        if not new_filter.keys()[0] in self.filter_names:
                            self.filter_names.append(new_filter.keys()[0])
                        self.extended_filters_per_x.update({s: new_filter})
        self._update()
        return None

    def add_y_on_y(self, name):
        """
        Produce aggregations crossing the (main) y variables with each other.

        Parameters
        ----------
        name: str
            key name for the y on y aggregation.

        Returns
        -------
        None
        """
        if not isinstance(name, str):
            raise TypeError("'name' attribute for add_y_on_y must be a str!")
        self.y_on_y = name
        self._update()
        return None

    def _map_x_to_y(self):
        """
        Combine all defined cross and downbreaks in a map.

        Returns
        -------
        None
        """
        def _extend(x, mapping):
            mapping[x] = org_copy.deepcopy(self.yks)
            if x in self.extended_yks_per_x:
                mapping[x].extend(self.extended_yks_per_x[x])
            if x in self.exclusive_yks_per_x:
                mapping[x] = self.exclusive_yks_per_x[x]

        mapping = OrderedDict()
        for x in self.xks:
            if x in self._meta['masks']:
                if x in self.summaries and not self.transposed_arrays.get(x):
                    mapping[x] = ['@']
                if x in self.transposed_arrays:
                    if '@' in mapping:
                        mapping['@'].extend([x])
                    else:
                        mapping['@'] = [x]
                for x2 in self.sources(x):
                    _extend(x2, mapping)
            else:
                _extend(x, mapping)
        self.x_y_map = mapping
        return None

    def _map_x_to_filter(self):
        """
        Combine all defined downbreaks with its beloning filter in a map.

        Returns
        -------
        None
        """
        mapping = OrderedDict()
        for x in self.xks:
            mapping[x] = org_copy.deepcopy(self.filter)
            if x in self.extended_filters_per_x:
                mapping[x] = self.extended_filters_per_x[x]
            if x in self._meta['masks']:
                xks = self.sources(x)
                for x2 in xks:
                    mapping[x2] = org_copy.deepcopy(self.filter)
                    if x2 in self.extended_filters_per_x:
                        mapping[x2] = self.extended_filters_per_x[x2]
        self.x_filter_map = mapping
        return None

    def _check_forced_names(self, variables):
        """
        Store forced names for xks and return adjusted list of downbreaks.

        Parameters
        ----------
        variables: list of str/dict/tuple
            Variables that are checked. If a dict or tupel is provided, the
            key/ first item is used as variable name and the value/ second
            item as forced name.

        Returns
        -------
        xks: list of str
        """
        xks = []
        renames = {}
        for x in variables:
            if isinstance(x, dict):
                xks.append(x.keys()[0])
                renames[x.keys()[0]] = x.values()[0]
            elif isinstance(x, tuple):
                xks.append(x[0])
                renames[x[0]] = x[1]
            else:
                xks.append(x)
            if not self.var_exists(xks[-1]):
                raise ValueError('{} is not in DataSet.'.format(xks[-1]))
        self.forced_names = renames
        return xks

    def _combine_filters(self, ext_filters):
        """
        Combines existing filter in ``self.filter`` with additional filters.

        Parameters
        ----------
        ext_filters: dict
            dict with variable name as key, str or tupel of str, and logic
            as value. For example:
            ext_filters = {'q1': {'gender': 1}}

        Returns
        -------
        new_filter: dict {'new_filter_name': intersection([old_logic, new_logic])}
        """
        old_filter = self.filter
        no_global_filter = old_filter == 'no_filter'
        if no_global_filter:
            combined_name = '(no_filter)+({})'.format(ext_filters.keys()[0])
            new_filter = {combined_name: ext_filters.values()[0]}
        else:
            old_filter_name = old_filter.keys()[0]
            old_filter_logic = old_filter.values()[0]
            new_filter_name = ext_filters.keys()[0]
            new_filter_logic = ext_filters.values()[0]
            combined_name = '({})+({})'.format(old_filter_name, new_filter_name)
            combined_logic = intersection([old_filter_logic, new_filter_logic])
            new_filter = {combined_name: combined_logic}
        return new_filter

    def _samplesize_from_batch_filter(self):
        """
        Calculates sample_size from existing filter.
        """
        f = self.filter
        if f == 'no_filter':
            self.sample_size = len(self._data.index)
        else:
            self.sample_size = len(self._dsfilter(self, 'sample', f.values()[0])._data.index)
        return None