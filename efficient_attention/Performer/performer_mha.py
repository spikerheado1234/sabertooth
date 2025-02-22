import sys
import os

import jax.numpy as jnp

import flax.linen as nn
from flax.linen.linear import DenseGeneral, default_kernel_init

import functools
from typing import (Any, Callable, Optional, Tuple)

sys.path.append(os.getcwd())

PRNGKey = Any
Shape = Tuple[int, ...]
Dtype = Any
Array = Any

import pdb ## For debugging purposes only.

class MHA(nn.Module):
    hidden_dim : int
    head_dim : int
    num_heads : int
    dropout : float
    mask : bool
    dtype: Optional[Dtype] = None
    param_dtype: Any = jnp.float32
    kernel_init: Callable[[PRNGKey, Shape, Dtype], Array] = default_kernel_init
    bias_init: Callable[[PRNGKey, Shape, Dtype], Array] = nn.initializers.zeros
    use_bias: bool = True
    precision: nn.linear.PrecisionLike = None
    numerical_stabilizer: float = 0.001
    up_train: bool = False

    """
    ## For some reason putting the initializers over here doesn't seem to work.
    ## They are somehow inextricably tied to the other variables defined above.
    ## It may be valuable to figure out why on earth this happens.
    query_kernel_init = jax.nn.initializers.glorot_normal()
    key_kernel_init = jax.nn.initializers.glorot_normal
    value_kernel_init = jax.nn.initializers.glorot_normal
    """

    @nn.compact
    def __call__(self, x, step, *, train):
        ## Jax complains about passing in multiple arguments.
        ## So we do the hack of concatenating the queries, keys and values into a list and unpacking it.
        query, key, value = x

        ## First, we map the queries keys and values.
        dense = functools.partial(DenseGeneral,
                                  axis=-1,
                                  dtype=self.dtype,
                                  param_dtype=self.param_dtype,
                                  features=(self.num_heads, self.head_dim),
                                  kernel_init=self.kernel_init,
                                  bias_init=self.bias_init,
                                  use_bias=self.use_bias,
                                  precision=self.precision)
        # project inputs_q to multi-headed q/k/v
        # dimensions are then [batch..., length, n_heads, n_features_per_head]
        queries, keys, values = (dense(name='query')(query),
                             dense(name='key')(key),
                             dense(name='value')(value))

        ## The following is taken directly from the Performer Code. ##
        ## source: https://github.com/google-research/google-research/blob/master/performer/fast_attention/tensorflow/fast_attention.py#L322 ##

        ## We then re-transform the queries and the keys.
        queries = nn.relu(queries) + self.numerical_stabilizer
        keys = nn.relu(keys) + self.numerical_stabilizer

        ## We then do a transposition. ##
        queries = jnp.transpose(queries, [1, 0, 2, 3])
        keys = jnp.transpose(keys, [1, 0, 2, 3])
        values = jnp.transpose(values, [1, 0, 2, 3])

        if self.mask:
            raise Exception("We have not implemented the Causal Attention Mechanism!")
        else:
            ## Non-causal numerator. ##
            kvs = jnp.einsum("lbhm,lbhd->bhmd", keys, values)
            a_v = jnp.einsum("lbhm,bhmd->lbhd", queries, kvs)
            ## Non-causal denominator. ##
            ks_sum = jnp.einsum("lbhm->bhm", keys)
            normalizer = jnp.einsum("lbhm,bhm->lbh", queries, ks_sum)
            ## Then we transpose back and do the normalization. ##
            a_v = jnp.transpose(a_v, [1, 0, 2, 3])
            normalizer = jnp.transpose(normalizer, [1, 0, 2])
            normalizer = jnp.expand_dims(normalizer, len(normalizer.shape))
            a_v = a_v / normalizer

        ## Finally, concatenate across the head dimension.
        out = DenseGeneral(features=self.hidden_dim,
                           axis=(-2, -1),
                           kernel_init=self.kernel_init,
                           bias_init=self.bias_init,
                           use_bias=self.use_bias,
                           dtype=self.dtype,
                           param_dtype=self.param_dtype,
                           precision=self.precision,
                           name='out')(a_v)
        return out

"""
## A place to unit test my Multi-Head-Attention Implementation.
## Unit tests are always great!
from jax import random

hidden_dim = 15
head_dim = 5
num_heads = 3
dropout = 0.1
mask = False 
mha = MHA(hidden_dim, head_dim, num_heads, dropout, mask)

batch_size = 2
sequence_length = 4
param_key = random.PRNGKey(42)
dropout_key = random.PRNGKey(43)
qs = random.uniform(random.PRNGKey(44), (batch_size, sequence_length, hidden_dim))
ks = random.uniform(random.PRNGKey(45), (batch_size, sequence_length, hidden_dim))
vs = random.uniform(random.PRNGKey(46), (batch_size, sequence_length, hidden_dim))
params = mha.init({'params': param_key}, [qs, ks, vs], train=True)
## One thing to keep note is that a new dropout_key must constantly be passed into the function.
attention_mat = mha.apply(params, [qs, ks, vs], train=True, rngs={'dropout': dropout_key})
## Further sanity checks.
print(attention_mat)
print(attention_mat.shape)
"""