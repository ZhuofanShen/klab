#!/usr/bin/python
from glob import glob
from math import pi, sqrt
import numpy as np
import pickle
from pyrosetta import *
from pyrosetta.rosetta.core.scoring.dssp import Dssp
from pyrosetta.rosetta.core.scoring import rmsd_atoms
from pyrosetta.rosetta.core.scoring import superimpose_pose
from pyrosetta.rosetta.core.select.residue_selector import ResidueIndexSelector
from pyrosetta.rosetta.core.simple_metrics.metrics import RMSDMetric
from pyrosetta.rosetta.core.simple_metrics.per_residue_metrics import PerResidueRMSDMetric
from pyrosetta.rosetta.protocols.simple_moves import SuperimposeMover

#init('-mute all, -ignore_zero_occupancy false')
#hcv_pose = pose_from_pdb('a_to_s_ly104_WT.pdb')
#hcv_cat_res = {72:'H', 96:'D', 154:'S'}
#tev = pose_from_pdb('tev.pdb')
tev_seq = 'GESLFKGPRDYNPISSTICHLTNESDGHTTSLYGIGFGPFIITNKHLFRRNNGTLLVQSLHGVFKVKNTTTLQQHLIDGRDMIIIRMPKDFPPFPQKLKFREPQREERICLVTTNFQTKSMSSMVSDTSCTFPSSDGIFWKHWIQTKDGQCGSPLVSTRDGFIVGIHSASNFTNTNNYFTSVPKNFMELLTNQEAQQWVSGWRLNADSVLWGGHKVFMSKP'
tev_cat_res = {'H': 46, 'A': 81, 'N': 151} # In pose: H39, D74, C144
# Map lists all loop regions, catalytic triad, all in PDB (not pose) numbers
# Had to generate manually since loops might contain beta-fingers
tev_map = {    'N':  range(  8,  18),
				 1:  range( 26,  28),
				 2:  range( 38,  39),
				 3:  range( 44,  54),
				 4:  range( 59,  63),
				 5:  range( 67,  74),
				 6:  range( 78,  82),
				 7:  range( 87, 109),
				 8:  range(117, 121),
				 9:  range(126, 139),
				10:  range(143, 152),
				11:  range(158, 161),
				12:  range(172, 176),
			   'C':  range(182, 221)}

htra1_map = {  'N':  range(160, 183),
				 1:  range(192, 198),
				 2:  range(209, 214),
				 3:  range(218, 226),
				 4:  range(233, 235),
				 5:  range(240, 241),
				 6:  range(247, 250),
				 7:  range(256, 276),
				 8:  range(284, 290),
				 9:  range(300, 317),
				10:  range(320, 329),
				11:  range(335, 337),
				12:  range(349, 351),
			   'C':  range(357, 370)}

def get_distance(c1, c2):
	""" Returns the distance between two Rosetts XYZ coordinate vectors"""
	dist = sqrt((c2.x - c1.x) ** 2 + (c2.y - c1.y) ** 2 + (c2.z - c1.z) ** 2)
	return dist


def find_res_ca_coords(pose, resnum):
	""" For a given pose and residue number, returns the coordinates of CA """
	residue = pose.residue(resnum)
	CA = residue.atom('CA')
	return CA.xyz()


def get_vector_obj_for_rmsa(pose, residue_number):
	"""
	For a given pose and residue number, returns a list of the vectors from CA 
	to N and CA to C.
	"""
	target_res = pose.residue(residue_number)
	CA_N_vector = list(target_res.atom('N').xyz()-target_res.atom('CA').xyz())
	CA_C_vector = list(target_res.atom('C').xyz()-target_res.atom('CA').xyz())

	return [CA_N_vector, CA_C_vector]


def get_section_RMSD(pose_1, selector_1, pose_2, selector_2):
	"""
	Calculates CA RMSD of pose regions. If selectors are given as none, will 
	calculate the whole pose.
	"""
	rmsd = PerResidueRMSDMetric()
	rmsd.set_rmsd_type(rmsd_atoms.rmsd_protein_bb_ca)
	rmsd.set_comparison_pose(pose_1)
	if selector_1:
		rmsd.set_residue_selector_reference(selector_1)
	if selector_2:
		rmsd.set_residue_selector(selector_2)
	
	return rmsd.calculate(pose_2)


#def get_rmsd(pose_1, pose_2, residues_1, residues_2):
	#assert len(residues_1) == len(residues_2)
	#n = len(residues_1)

	#difs = 0
	#for i in range(n):
	#	r1_coords = find_res_ca_coords(pose_1, residues_1[i])
	#	r2_coords = find_res_ca_coords(pose_2, residues_2[i])
	#	difs += (r2_coords.x - r1_coords.x) ** 2
	#	difs += (r2_coords.y - r1_coords.y) ** 2
	#	difs += (r2_coords.z - r1_coords.z) ** 2

	#return sqrt(difs / n)


def find_cat_res(pose):
	""" 
	For a given pose, checks the coordinates of each CA for closest match to 
	the catalytic residues of HCV protease. Returns the corresponding residue 
	for each of the three members of the triad.
	"""
	HCV_coords = [find_res_ca_coords(hcv_pose, x) for x in cat_res]
	matching_residue_dists = ['none', 'none', 'none']
	matching_residue_numbers = ['none', 'none', 'none']
	chain_length = pose.total_residue()

	# Checking each residue against all members of the catalytic triad
	for resnum in range(1, chain_length + 1):
		res_coord = find_res_ca_coords(pose, resnum)
		for n, hcv_coord in enumerate(HCV_coords):
			distance = get_distance(hcv_coord, res_coord)
			if matching_residue_dists[n] > distance:
				matching_residue_dists[n] = distance
				matching_residue_numbers[n] = resnum

	# Listing matched residue numbers and residue types
	catalytic_matches = {}
	for res in matching_residue_numbers:
		catalytic_matches[res] = str(pose.residue(res).name1())

	return catalytic_matches


def get_secstruct(pose):
	""" Uses DSSP to get a secondary structure string for the given pose """
	sec_struct = Dssp(pose)
	sec_struct.insert_ss_into_pose(pose)
	ss = str(pose.secstruct())

	return ss


def align_protein_sections(pose_1, selector_1, pose_2, selector_2):
	"""
	Aligns selected regions of two poses, superimposing the second pose onto 
	the first, based on CA RMSD. Returns the RMSD value.
	"""
	prmsd = PerResidueRMSDMetric()
	prmsd.set_rmsd_type(rmsd_atoms.rmsd_protein_bb_ca)
	prmsd.set_comparison_pose(pose_1)
	prmsd.set_residue_selector_reference(selector_1)
	prmsd.set_residue_selector(selector_2)
	amap = prmsd.create_atom_id_map(pose_2)
	
	return superimpose_pose(pose_2, pose_1, amap)


def make_subpose(pose, start=1, end=1):
	""" Return pose that is a section of another pose """
	# Set end if not given
	if end == 1:
		end = pose.total_residue()

	# Make new subpose
	subpose = Pose(pose, start, end)

	return subpose

#def align_proteins(pose_1, pose_2):
	""" 
	Aligns two proteins usinf the Superimpose mover. The second protein will be 
	aligned to the first. Accommodates proteins of different sizes by aligning 
	only the number of residues in the smaller protein. This assumes that the 
	difference between the sizes is much smaller than the total number of 
	residues in each.
	"""
	# Determining the size of the smaller pose
	#min_length = min(pose_1.total_residue(), pose_2.total_residue())

	# Creating mover from start to the smaller end, aligning with all BB atoms
	#sim = SuperimposeMover(pose_1, min_length, 190, min_length, 190, False)

	#sim.apply(pose_2)
	#return


#def insert_loop(scaffold, insert, )


################################################################################
# RMSA functions provided by Will Hansen
#INPUTS: list of pairable vectors. Obj1 should be a list of vectors
#that you want to match to the corresponding obj2.
def vector_angle(v1, v2):
	v1_u = v1 / np.linalg.norm(v1)
	v2_u = v2 / np.linalg.norm(v2)
	return np.arccos(np.clip(np.dot(v1_u, v2_u), -1.0, 1.0))

def zero_vector_pair(v_pair):
	trans = [0. - v_pair[0], 0. - v_pair[1], 0. - v_pair[2]]
	new_pair = []
	for point in v_pair:
		new_point = np.array(point) + np.array(trans)
		new_pair.append(new_point)
	return new_pair

def calc_rmsa(obj1, obj2, ratio=(pi/6.0)):
	assert len(obj1) == len(obj2)
	compare_vectors = zip(obj1, obj2)
	vector_ang_sum = 0.0
	for vector_pairs in compare_vectors:
		vector1 = zero_vector_pair(vector_pairs[0])
		vector2 = zero_vector_pair(vector_pairs[1])
		vector_ang_sum += vector_angle(np.array(vector1[1]), np.array(vector2[1]))
	rmsa = ((vector_ang_sum/ratio)**2 / len(obj1))**0.5
	return rmsa
################################################################################


class protease_info():
	def __init__(self, qname, qpose, sname, spose):
		self.query_name = qname.upper()
		self.query_pose = qpose
		self.subject_name = sname.upper()
		self.subject_pose = spose

		# Dali info
		self.Z_score = None
		self.rmsd = None
		self.lali = None
		self.nres = None
		self.pID = None
		self.description = None

		# Alignment
		self.alignment = None
		self.aligned_residues = []

		# Catalytic triad
		self.nucleophile_res = None
		self.nucleophile_type = None
		self.catalytic_his = None
		self.catalytic_his_type = None
		self.catalytic_acid = None
		self.catalytic_acid_type = None

		# Loops
		self.loop_maps = {}

		self.auto_calculate()

	def auto_calculate(self, dali_file='aligned_pdbs/0000_dali_pdb90_tev.txt', align_file='aligned_pdbs/0000_seq_align.txt', q_cat_res=tev_cat_res, structure_map=tev_map):
		""" Run all the calculation functions """
		self.get_dali_info(dali_file=dali_file)
		self.get_alignment(align_file=align_file)
		self.map_aligned_residues()
		self.map_cat_res(q_cat_res=q_cat_res)
		self.map_structure_elements(structure_map=structure_map)

		return

	def get_dali_info(self, dali_file='aligned_pdbs/0000_dali_pdb90_tev.txt'):
		"""
		Read in appropriate summary from Dali download about this protein, 
		including Z score (indicating structural similarity to the query 
		structure), RMSD to TEV protease (the original query), lali (the number 
		of structurally equivalent CA atoms), nres (the total number of 
		residues in the chain), pID (percentage of identical amino acids in 
		equivalent residues), and PDB description.
		Header line:
		Chain   Z	rmsd lali nres  %id Description
		"""
		# Read in Dali summary
		with open(dali_file, 'r') as r:
			match_summaries = r.readlines()

		# Find appropriate line in the summary by PDB name, stopping when found
		summary_line = None
		for ms in match_summaries:
			if self.subject_name in ms.upper():
				summary_line = ms.split()
				break

		# If no appropriate line is found, print error message and exit
		if summary_line == None:
			print("No matching protein identified in Dali summary")
			return

		# If line was found, read in its values
		self.Z_score = summary_line[1]
		self.rmsd = summary_line[2]
		self.lali = summary_line[3]
		self.nres = summary_line[4]
		self.pID = summary_line[5]
		self.description = ' '.join(summary_line[6:])

		return

	def get_alignment(self, align_file='aligned_pdbs/0000_seq_align.txt'):
		"""
		Read in sequence alignment file as a set of contiguous strings
		Hacky--may need tweaking to generalize.

		Alignment file has sets of five lines, with each set covering 60 
		residues in the alignment. The first line (0) is the secondary 
		structure of the query (TEV). The second (1) is the query sequence. The
		third (2) is the identity match (indicated as positive by |). The 
		fourth (3) is the subject sequence. The fifth (4) is the subject 
		secondary structure.
		"""
		# Read in sequence alignment
		with open(align_file, 'r') as r:
			seq_aligns = r.readlines()

		# Find appropriate lines in the summary by PDB name
		begin_block = None
		end_block = None
		for n, sa in enumerate(seq_aligns):
			# Only check starting lines
			if 'Z-score' in sa:
				# Stop capture at the next block after finding the start
				if begin_block != None:
					end_block = n 
					break
				# Find beginning of block, where start line includes name
				if self.subject_name in sa.upper():
					begin_block = n

		# Extracting relevant text block
		alignment_block = seq_aligns[begin_block:end_block]
		# Cleaning block
		abclean = [i.strip() for i in alignment_block[2:] if i != '\n']
		# Chack that there are the right number of lines
		assert len(abclean) % 5 == 0 

		# Concatenating data portions of each alignment line. See docstring.
		align_lines = {0: '', 1: '', 2: '', 3: '', 4: ''}
		for n, line in enumerate(abclean):
			which_set = n % 5
			# Cut off before residue numbers
			if which_set == 0:
				max_len = len(line)
			# Pad short lines
			line_info = line[6:max_len]
			while len(line_info) < max_len - 6:
				line_info += ' '
			# Adding to appropriate set
			align_lines[which_set] += line_info

		# Verifying all lines are equal length
		line_lengths = [len(i) for i in align_lines.values()]
		assert all([elem == line_lengths[0] for elem in line_lengths])

		self.alignment = list(align_lines.values())
		return

	def map_aligned_residues(self):
		"""
		Feed alignment data into a list of aligned_residues, each with 
		corresponding information about the position in both query and the 
		protease being analyzed.

		Start by finding the first five residues of the alignment in the pose 
		sequence for both query and the subject (adding 1 because Rosetta is 
		1-indexed). This is necessary because Dali only includes aligned 
		regions, whereas some subjects might have large N-terminal domains.
		"""
		# Get query residue number for beginning of alignment
		quer_match_seq = self.alignment[1].replace('-','').upper().replace('X','')
		quer_pose_seq = self.query_pose.sequence()
		assert quer_match_seq[:6] in quer_pose_seq
		quer_pose_num = quer_pose_seq.find(quer_match_seq[:6]) 

		# Get subject residue number for beginning of alignment
		subj_match_seq = self.alignment[3].replace('-','').upper().replace('X','')
		subj_pose_seq = self.subject_pose.sequence()
		assert subj_match_seq[:6] in subj_pose_seq
		subj_pose_num = subj_pose_seq.find(subj_match_seq[:6])

		# Loop through each residue in the alignment, adding aligned_residue
		# objects to the list for each
		quer_info = self.query_pose.pdb_info()
		subj_info = self.subject_pose.pdb_info()
		for i in range(len(self.alignment[0])):
			# Check whether there is a query residue in the alignment
			if self.alignment[1][i] not in ['-', 'x', 'X']:
				# Increment query pose number
				quer_pose_num += 1
				temp_quer_pose_num = quer_pose_num
				# Get query PDB number
				quer_pdb_num = int(quer_info.pose2pdb(quer_pose_num).split()[0])
				# Get query secondary structure
				quer_dss = self.alignment[0][i].upper()
				# Get query residue letter
				quer_sequence = self.alignment[1][i] # Case left to check align
			else:
				temp_quer_pose_num = None
				quer_pdb_num = None
				quer_dss = None
				quer_sequence = None

			# Check whether there is a subject residue in the alignment
			if self.alignment[3][i] not in ['-', 'x', 'X']:
				# Increment subject pose number
				subj_pose_num += 1
				temp_subj_pose_num = subj_pose_num
				# Get subject PDB number
				subj_pdb_num = int(subj_info.pose2pdb(subj_pose_num).split()[0])
				# Get subject secondary structure
				subj_dss = self.alignment[4][i].upper()
				# Get subject residue letter
				subj_sequence = self.alignment[3][i] # Case left to check align
			else:
				temp_subj_pose_num = None
				subj_pdb_num = None	
				subj_dss = None
				subj_sequence = None

			# Collect residue identity
			res_identity = self.alignment[2][i]

			# Populating aligned_residue object
			a_residue = aligned_residue(
				temp_quer_pose_num, quer_pdb_num, 
				quer_dss, quer_sequence,
				temp_subj_pose_num, subj_pdb_num, 
				subj_dss, subj_sequence, 
				res_identity)

			# Adding aligned_residue object to self.aligned_residues
			self.aligned_residues.append(a_residue)

		return

	def map_cat_res(self, q_cat_res=tev_cat_res):
		"""
		Using the list of aligned residues, identify the residues in the subject 
		pose that match the query. Requires an input for the catalytic triad in 
		the form of a dict, H: histidine, A: acid residue, N: nucleophile, using 
		PDB (not pose) numbering.
		"""
		# Initialize list of matched catalytic residues as all None
		subject_cat_nums = {'H': None, 'A': None, 'N': None} 
		subject_cat_name = {'H': None, 'A': None, 'N': None} 

		# Collect list of just the aligned_residue objects for the catalytic 
		# residues, based on 
		cat_matches = []
		for ar in self.aligned_residues:
			if ar.query_pdb_number in q_cat_res.values():
				cat_matches.append(ar)

		# Match catalytic residues, update subject_cat dicts
		for typ, num in q_cat_res.items():
			for cm in cat_matches:
				if cm.query_pdb_number == num:
					if cm.subject_pdb_number: # Remains None, if no match
						subject_cat_nums[typ] = cm.subject_pdb_number
						subject_cat_name[typ] = cm.subject_res_type

		# Set attribute values
		if subject_cat_name['N'] in ['A', 'C', 'S']:
			self.nucleophile_res = subject_cat_nums['N']
			self.nucleophile_type = subject_cat_name['N']
		if subject_cat_name['H'] in ['H']:
			self.catalytic_his = subject_cat_nums['H']
			self.catalytic_his_type = subject_cat_name['H'] # Should always become H
		if subject_cat_name['A'] in ['D', 'E']:
			self.catalytic_acid = subject_cat_nums['A']
			self.catalytic_acid_type = subject_cat_name['A']

		return

	def map_structure_elements(self, structure_map=tev_map):
		"""
		
		"""
		loop_maps = {}
		last_loop = max([x for x in structure_map.keys() if not isinstance(x, str)])
		for loop in structure_map:
			# Get boundaries
			# One past the last residue of upstream loop
			# One before the first residue of downstream loop
			if loop == 'N':
				n_bound = None
				c_bound = structure_map[1][0] - 1
			elif loop == 'C':
				n_bound = structure_map[last_loop][-1] + 1
				c_bound = None
			elif loop == 1:
				n_bound = structure_map['N'][-1] + 1
				c_bound = structure_map[loop + 1][0] - 1
			elif loop == last_loop:
				n_bound = structure_map[loop - 1][-1] + 1
				c_bound = structure_map['C'][0] - 1
			else:
				n_bound = structure_map[loop - 1][-1] + 1
				c_bound = structure_map[loop + 1][0] - 1

			loop_map = matched_loop(self.query_pose, self.subject_pose, 
				self.aligned_residues, self.subject_name, loop, structure_map[loop], n_bound, c_bound)
			loop_maps[loop] = loop_map

		self.loop_maps = loop_maps

		return


class aligned_residue():
	"""
	Data storage structure for a single residue. Includes information about 
	both the target residue in its own protein and the corresponding aligned 
	residue in the query structure. Information includes secondary structure, 
	whether residues are structurally matched (as opposed to unaligned), and 
	whether the residues are identical. Also stores residue numbers (both PDB
	and pose) for both residues.
	"""
	def __init__(self, qpnum, qrnum, qdss, qseq, spnum, srnum, sdss, sseq, rid):
		self.query_pose_number = qpnum
		self.query_pdb_number = qrnum
		self.query_sec_struct = qdss
		if qseq:
			self.query_res_type = qseq.upper()
		else: 
			self.query_res_type = None

		self.subject_pose_number = spnum
		self.subject_pdb_number = srnum
		self.subject_sec_struct = sdss
		if sseq:
			self.subject_res_type = sseq.upper()
		else: 
			self.subject_res_type = None

		# Determine whether residues are structurally aligned, based on case
		if all([qseq, sseq]):
			if   all([i == i.upper() for i in [qseq, sseq]]):
				self.residues_align = True
			elif all([i == i.lower() for i in [qseq, sseq]]):
				self.residues_align = False
			else:
				print('Residue cases do not match')
				print(spnum, sseq, qpnum, qseq)
				assert False
		else:
			self.residues_align = False

		# Determine res identity, based on whether connection line was drawn
		if rid == '|':
			self.residues_equal = True
			assert self.query_res_type == self.subject_res_type
		else:
			self.residues_equal = False


class matched_loop():
	"""
	Data storage structure for loops. When taking in a loop of a query 
	structure, finds the edges bordering it (usually B-sheets) and looks for 
	residue matches within the given boundaries, which should be the starts of
	the next loops. Input residues should use PDB (not pose) numbers.
	"""
	def __init__(self, query_pose, subject_pose, aligned_residues, source, l_name, l_range, n_bound, c_bound):
		self.loop_name = l_name
		self.loop_source = source

		self.query_loop_start = l_range[0]
		self.query_loop_end = l_range[-1]
		if n_bound:
			self.query_n_boundary = n_bound
		else: 
			self.query_n_boundary = aligned_residues[0].query_pdb_number
		if c_bound:
			self.query_c_boundary = c_bound
		else:
			self.query_c_boundary = aligned_residues[-1].query_pdb_number

		# Flanking residues
		self.n_boundary = None
		self.c_boundary = None
		self.query_nearest_n_match = None
		self.query_nearest_n_b_match = None
		self.query_farthest_n_match = None
		self.query_farthest_n_b_match = None
		self.subject_nearest_n_match = None
		self.subject_nearest_n_b_match = None
		self.subject_farthest_n_match = None
		self.subject_farthest_n_b_match = None
		self.query_nearest_c_match = None
		self.query_nearest_c_b_match = None
		self.query_farthest_c_match = None
		self.query_farthest_c_b_match = None
		self.subject_nearest_c_match = None
		self.subject_nearest_c_b_match = None
		self.subject_farthest_c_match = None
		self.subject_farthest_c_b_match = None
		n_matches, c_matches, loop_res = self.collect_loop_match(aligned_residues)

		# Overlaps
		self.n_overlap_is_b = None
		self.n_overlap_size = None
		self.c_overlap_is_b = None
		self.c_overlap_size = None
		self.check_overlaps()

		# Loop proximity to peptide substrate
		self.loop_near_substrate = None
		self.closest_residue_distance = None
		self.close_substrate_residues = []
		self.residue_count = None
		self.feature_size = None
		if query_pose.num_chains() == 2:
			self.find_proximity_to_substrate(query_pose, subject_pose, loop_res)

		# Best matched residues for loop swap
		self.query_N_splice_res = None
		self.subject_N_splice_res = None
		self.query_C_splice_res = None
		self.subject_C_splice_res = None
		self.query_loop_size = None
		self.subject_loop_size = None
		#if all([len(n_matches) != 0, len(c_matches) != 0]):
		#	self.match_loop_endpoints(self, query_pose, subject_pose, n_matches, c_matches)
		self.simple_pick_splice()

		# Eliminate overly similar loops
		self.subject_loop_matches_query_length = None
		self.rmsd = None
		self.check_loop_rmsd(query_pose, subject_pose, loop_res)

		# Evaluate whether loop is a suitable target
		self.is_near_target = None
		self.is_not_domain = None
		self.is_n_match = None
		self.is_c_match = None
		self.is_possible_target = None
		self.evaluate_suitability()

	def get_loop_range(self, aligned_residues):
		"""
		Take subset of aligned residues near loop, ending at the query residues 
		given at construction. If no boundary (N or C terminus), collects 
		everything to the end.
		"""
		# Collecting N-terminal end of neighborhood
		for ar in aligned_residues:
			if ar.query_pdb_number == self.query_n_boundary:
				range_start = aligned_residues.index(ar)
				break


		# Collecting C-terminal end of neighborhood
		for ar in aligned_residues[::-1]:
			if ar.query_pdb_number == self.query_c_boundary:
				range_end = aligned_residues.index(ar)
				break

		# Return subset of aligned residues
		return aligned_residues[range_start: range_end]

	def collect_loop_match(self, aligned_residues):
		"""
		"""
		# Get neighborhood subset of aligned residues near loop
		loop_neighboorhood_alignment = self.get_loop_range(aligned_residues)

		# Determine N-terminal boundary of subject loop based on most N-terminal 
		# residue matching the query. Trim loop_neighboorhood_alignment to match.
		for ar in loop_neighboorhood_alignment:
			# Defaults to first residue in the set
			if not self.n_boundary:
				if ar.subject_pdb_number:
					self.n_boundary = ar.subject_pdb_number
			# Moves in if a closer matching residue is found
			if ar.residues_align:
				self.n_boundary = ar.subject_pdb_number
				break
			else:
				loop_neighboorhood_alignment.remove(ar)

		# Determine C-terminal boundary of subject loop based on most C-terminal 
		# residue matching the query. Trim loop_neighboorhood_alignment to match.
		for ar in loop_neighboorhood_alignment[::-1]:
			# Defaults to first residue in the set
			if not self.c_boundary:
				if ar.subject_pdb_number:
					self.c_boundary = ar.subject_pdb_number
			# Moves in if a closer matching residue is found
			if ar.residues_align:
				self.c_boundary = ar.subject_pdb_number
				break
			else:
				loop_neighboorhood_alignment.remove(ar)

		# Take terminal subsets of loop_neighboorhood_alignment
		first_loop_res = 0
		last_loop_res = -2
		for ar in loop_neighboorhood_alignment:
			if ar.query_pdb_number:
				if ar.query_pdb_number == self.query_loop_start:
					first_loop_res = loop_neighboorhood_alignment.index(ar)
				if ar.query_pdb_number == self.query_loop_end:
					last_loop_res = loop_neighboorhood_alignment.index(ar)

		# Take flanking sets, adjusting for edge cases
		if self.query_n_boundary:
			n_neighbor_list = loop_neighboorhood_alignment[:first_loop_res]
		else:
			n_neighbor_list = []
		if self.query_c_boundary:
			c_neighbor_list = loop_neighboorhood_alignment[last_loop_res + 1 :]
		else:
			c_neighbor_list = []
		loop_list = loop_neighboorhood_alignment[first_loop_res:last_loop_res + 1]

		# Find matching residues on N-terminal side, going away from loop
		for nn in n_neighbor_list[::-1]:
			if nn.residues_align:
				self.query_farthest_n_match = nn.query_pdb_number
				self.subject_farthest_n_match = nn.subject_pdb_number
				if not self.subject_nearest_n_match:
					self.query_nearest_n_match = nn.query_pdb_number
					self.subject_nearest_n_match = nn.subject_pdb_number
				if nn.subject_sec_struct == 'E':
					self.query_farthest_n_b_match = nn.query_pdb_number
					self.subject_farthest_n_b_match = nn.subject_pdb_number
					if not any([self.query_nearest_n_b_match, self.subject_nearest_n_b_match]):
						self.query_nearest_n_b_match = nn.query_pdb_number
						self.subject_nearest_n_b_match = nn.subject_pdb_number
			else:
				n_neighbor_list.remove(nn)

		# Find matching residues on C-terminal side, going away from loop
		for cn in c_neighbor_list:
			if cn.residues_align:
				self.query_farthest_c_match = cn.query_pdb_number
				self.subject_farthest_c_match = cn.subject_pdb_number
				if not self.subject_nearest_c_match:
					self.query_nearest_c_match = cn.query_pdb_number
					self.subject_nearest_c_match = cn.subject_pdb_number
				if cn.subject_sec_struct == 'E':
					self.query_farthest_c_b_match = cn.query_pdb_number
					self.subject_farthest_c_b_match = cn.subject_pdb_number
					if not any([self.query_nearest_c_b_match, self.subject_nearest_c_b_match]):
						self.query_nearest_c_b_match = cn.query_pdb_number
						self.subject_nearest_c_b_match = cn.subject_pdb_number
			else:
				c_neighbor_list.remove(cn)

		# Final prune-out of unmatched residues
		n_neighbor_list = [nn for nn in n_neighbor_list if nn.residues_align]
		c_neighbor_list = [cn for cn in c_neighbor_list if cn.residues_align]

		return n_neighbor_list, c_neighbor_list, loop_list

	def find_proximity_to_substrate(self, query_pose, subject_pose, loop_residues):
		"""
		Finds all CA-CA distances between the coordinates of the substrate peptide
		"""
		substrate_coords = []
		loop_coords = []

		# Populating list of CA coordinates of substrate peptide
		substrate_chain = query_pose.split_by_chain()[2]
		for i in range(1, substrate_chain.total_residue() + 1):
			substrate_coords.append(find_res_ca_coords(substrate_chain, i))

		# Populating list of CA coordinates of loop
		for lr in loop_residues:
			if lr.subject_pose_number:
				loop_coords.append(find_res_ca_coords(subject_pose, lr.subject_pose_number))

		# Finding close residues
		closest_distance = 1000 # Arbitrary large number
		nearby_substrate_residues = []
		for n, sr in enumerate(substrate_coords):
			for lr in loop_coords:
				substrate_dist = get_distance(sr, lr)
				if substrate_dist < closest_distance:
					closest_distance = substrate_dist
				if substrate_dist <= 8:
					if (n + 1) not in nearby_substrate_residues:
						nearby_substrate_residues.append(n + 1)

		# Determine largest 1D length of feature
		max_interres_distance = 0
		for lc in loop_coords:
			for partner in [x for x in loop_coords if x != lc]:
				interres_dist = get_distance(lc, partner)
				if interres_dist > max_interres_distance:
					max_interres_distance = interres_dist

		# Updating attributes
		self.loop_near_substrate = bool(nearby_substrate_residues) 
		self.closest_residue_distance = closest_distance
		self.close_substrate_residues = nearby_substrate_residues
		self.residue_count = len(loop_coords)
		self.feature_size = max_interres_distance

		return

	def match_loop_endpoints(self, query_pose, subject_pose, n_matches, c_matches):
		"""
		Use average of RMSA and RMSD for each residue pair to determine best 
		matched residues on subject loop to superimpose with query loop.
		"""
		best_n_res = None
		best_c_res = None
		best_fit = 1000 # Arbitrary high number

		for nr in n_matches:
			# Getting N-side RMSA
			q_n_vect = get_vector_obj_for_rmsa(query_pose, nr.query_pose_number)
			s_n_vect = get_vector_obj_for_rmsa(subject_pose, nr.subject_pose_number)
			n_rmsa = calc_rmsa(q_n_vect, s_n_vect)

			for cr in c_matches:
				# Getting C-side RMSA
				q_c_vect = get_vector_obj_for_rmsa(query_pose, cr.query_pose_number)
				s_c_vect = get_vector_obj_for_rmsa(subject_pose, cr.subject_pose_number)
				c_rmsa = calc_rmsa(q_c_vect, s_c_vect)

				# Calculate RMSD
				rmsd = get_rmsd(query_pose, subject_pose, 
					[nr.query_pose_number, cr.query_pose_number], 
					[nr.subject_pose_number, cr.subject_pose_number])

				# Calculate fit value as average of RMSAs and RMSD
				fit_val = np.mean([np.mean([n_rmsa, c_rmsa]), rmsd])

				# Check against selected residues
				if fit_val < best_fit:
					best_n_res = nr
					best_c_res = cr
					best_fit = fit_val

		# Updating attributes with best splice residues
		self.query_N_splice_res = best_n_res.query_pose_number
		self.query_C_splice_res = best_c_res.query_pose_number
		self.subject_N_splice_res = best_n_res.subject_pose_number
		self.subject_C_splice_res = best_c_res.subject_pose_number

		return

	def check_overlaps(self):
		""" 
		Determines range of overlapping matched residues from the nearest 
		matched residue flanking the loop to the farthest, on both N-terminal 
		and C-terminal sides of the loop. 
		"""
		# Check N-term side for identified matching beta residues, taking that 
		# difference if available, difference of aligned loop residues otherwise
		if self.subject_nearest_n_b_match:
			self.n_overlap_is_b = True
			self.n_overlap_size = 1 + self.subject_farthest_n_b_match - \
										self.subject_nearest_n_b_match 
		else:
			self.n_overlap_is_b = False
			# Only assign overlap if aligned residues are found
			if self.subject_nearest_n_match:
				self.n_overlap_size = 1 + self.subject_farthest_n_match - \
										self.subject_nearest_n_match

		# Check C-term side for identified matching beta residues, taking that 
		# difference if available, difference of aligned loop residues otherwise
		if self.subject_nearest_c_b_match:
			self.c_overlap_is_b = True
			self.c_overlap_size = 1 + self.subject_farthest_c_b_match - \
										self.subject_nearest_c_b_match 
		else:
			self.c_overlap_is_b = False
			# Only assign overlap if aligned residues are found
			if self.subject_nearest_c_match:
				self.c_overlap_size = 1 + self.subject_farthest_c_match - \
										self.subject_nearest_c_match

	def simple_pick_splice(self):
		"""
		"""
		# Setting loop boundaries at closest matching residues, prioritizing 
		# b-sheet residues over unstructured ones
		if self.query_nearest_n_b_match:
			self.query_N_splice_res = self.query_nearest_n_b_match
			self.subject_N_splice_res = self.subject_nearest_n_b_match
		else:
			self.query_N_splice_res = self.query_nearest_n_match
			self.subject_N_splice_res = self.subject_nearest_n_match
		if self.query_nearest_c_b_match:
			self.query_C_splice_res = self.query_nearest_c_b_match
			self.subject_C_splice_res = self.subject_nearest_c_b_match
		else:
			self.query_C_splice_res = self.query_nearest_c_match
			self.subject_C_splice_res = self.subject_nearest_c_match

		# Determining length of query loop from identified boundaries
		if all([self.query_N_splice_res, self.query_C_splice_res]):
			self.query_loop_size = self.query_C_splice_res - self.query_N_splice_res
		elif self.query_N_splice_res:
			self.query_loop_size = self.query_c_boundary - self.query_N_splice_res
		elif self.query_C_splice_res:
			self.query_loop_size = self.query_C_splice_res - self.query_n_boundary
		else:
			self.query_loop_size = self.query_c_boundary - self.query_n_boundary

		# Determining length of subject loop from identified boundaries
		if all([self.subject_N_splice_res, self.subject_C_splice_res]):
			self.subject_loop_size = self.subject_C_splice_res - self.subject_N_splice_res
		elif self.subject_N_splice_res:
			self.subject_loop_size = self.c_boundary - self.subject_N_splice_res
		elif self.subject_C_splice_res:
			self.subject_loop_size = self.subject_C_splice_res - self.n_boundary
		else:
			self.subject_loop_size = self.c_boundary - self.n_boundary

		return

	def check_loop_rmsd(self, query_pose, subject_pose, loop_res):
		""" 
		If the subject and query loops are the same size, take CA RMSD 
		"""
		if self.query_loop_size == self.subject_loop_size:
			self.subject_loop_matches_query_length = True
			# Get pose-numbered residues for loop termini
			for lr in loop_res:
				if self.query_N_splice_res == lr.query_pdb_number:
					qn = lr.query_pose_number
					sn = lr.subject_pose_number
				if self.query_C_splice_res == lr.query_pdb_number:
					qc = lr.query_pose_number
					sc = lr.subject_pose_number

			# Make residue selectors for loops
			stemp = '{}-{}'
			query_selector = ResidueIndexSelector(stemp.format(qn, qc))
			subject_selector = ResidueIndexSelector(stemp.format(sn, sc))

			# Calculate RMSD
			self.rmsd = get_section_RMSD(query_pose, query_selector, 
										subject_pose, subject_selector)
		else:
			self.subject_loop_matches_query_length = False

		return

	def evaluate_suitability(self):
		proximity_check = bool(self.close_substrate_residues)
		res_count_check = self.subject_loop_size <= 50
		#res_count_check = self.residue_count <= 50
		#size_check = self.feature_size <= 50

		similarity_check = not (self.rmsd and self.rmsd < 0.2)

		if self.loop_name == 'N':
			n_match_check = True
		else:
			n_match_check = bool(self.subject_N_splice_res)

		if self.loop_name == 'C':
			c_match_check = True
		else:
			c_match_check = bool(self.subject_C_splice_res)

		# Updating attributes
		self.is_near_target = proximity_check
		self.is_not_domain = res_count_check
		self.is_different_from_original = similarity_check
		self.is_n_match = n_match_check
		self.is_c_match = c_match_check
		self.is_possible_target = all([proximity_check, res_count_check, 
			similarity_check, n_match_check, c_match_check])
		#self.is_possible_target = all([proximity_check, res_count_check, size_check, n_match_check, c_match_check])

		return



"""
pdb_list = glob('aligned_pdbs/*.pdb')
pdb_list.sort()
pdb_list.remove('aligned_pdbs/0000_master_pdb.pdb')
db_collect = []
for i in pdb_list:
	print(i)
	try:
		subj_name = i.replace('aligned_pdbs/','').replace('.pdb', '')
		subj_pose = pose_from_pdb(i)
		pinf = protein_loop_alignment.protease_info('TEV', tev, subj_name, subj_pose)
		pinf.auto_calculate()
		db_collect.append(pinf)
	except:
		print(i, 'failed')

outfile = 'protease_db.pkl'
with open(outfile, 'wb') as o:
	pickle.dump(db_collect, o)

with open('protease_database.csv', 'w') as w:
	header = ['query', 'subject', 'Z_score', 'rmsd', 'lali', 'nres', 'pID']
	header += ['cat_nucleophile', 'cat_his', 'cat_acid']
	for k in tev_map.keys():
		header += ['loop', 'length', 'potential_target', 'query_range', 'subject_range', 'reasons_rejected']
	w.write(', '.join(header) + '\n')

with open('protease_database.csv', 'a') as w:
	for i in db_collect:
		line_info = []
		line_info = [i.query_name, i.subject_name, i.Z_score, i.rmsd, i.lali, i.nres, i.pID]
		if i.nucleophile_res:
			line_info.append(i.nucleophile_type + str(i.nucleophile_res))
		else:
			line_info.append('None')
		if i.catalytic_his:
			line_info.append(i.catalytic_his_type + str(i.catalytic_his))
		else:
			line_info.append('None')
		if i.catalytic_acid:
			line_info.append(i.catalytic_acid_type + str(i.catalytic_acid))
		else:
			line_info.append('None')
		for k in i.loop_maps.keys():
			header += ['loop', 'length', 'swap_target', 'query_range', 'subject_range']
			line_info += [k, i.loop_maps[k].residue_count, i.loop_maps[k].is_possible_target]
			if i.loop_maps[k].is_possible_target:
				line_info.append('-'.join([str(x) for x in [i.loop_maps[k].query_N_splice_res, i.loop_maps[k].query_C_splice_res]]))
				line_info.append('-'.join([str(x) for x in [i.loop_maps[k].subject_N_splice_res, i.loop_maps[k].subject_C_splice_res]]))
				line_info += ['']
			else:
				line_info += ['', '']
				reject_reasons = []
				if not i.loop_maps[k].is_near_target:
					reject_reasons.append('Distance')
				if not i.loop_maps[k].is_not_domain:
					reject_reasons.append('Size')
				if not i.loop_maps[k].is_n_match:
					reject_reasons.append('No N match')
				if not i.loop_maps[k].is_c_match:
					reject_reasons.append('No C match')
				line_info.append('; '.join(reject_reasons))
		line_info = [str(i) for i in line_info]
		w.write(', '.join(line_info) + '\n')

"""

"""

only allow D&E for acids
"""