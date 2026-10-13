/*
	Filename: fir.h
		Header file
		FIR lab wirtten for WES/CSE237C class at UCSD.

*/
#ifndef FIR_H_
#define FIR_H_
#include <ap_int.h>

const unsigned short int N=128;

typedef ap_int<8> coef_t;
typedef short int data_t;
typedef ap_int<16> acc_t;

void fir (
  data_t *y,
  data_t x
  );

#endif
